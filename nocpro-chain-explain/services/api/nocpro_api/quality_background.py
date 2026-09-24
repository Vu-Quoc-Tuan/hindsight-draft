"""Snapshot-wide deterministic quality scheduling.

The HTTP workspace is intentionally bound to the snapshot currently selected
in the UI.  That is the right boundary for request-scoped evidence, but it is
not a suitable queue for the snapshot portfolio: merely opening a snapshot
must not be what starts its analysis.  This module owns one short-lived
Workspace per snapshot so packages, caches, and executor callbacks cannot
cross-contaminate the active UI workspace.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from contextlib import suppress
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from libs.contracts.topology_identity import effective_topology_version, snapshot_topology_profile

from .catalog import list_catalog_presets, load_preset_payload
from .quality_freshness import terminal_quality_row_is_current
from .workspace import Workspace, _topology_version


LOGGER = logging.getLogger(__name__)


def _source_activation_topology_is_complete(source: _SnapshotSource) -> bool:
    """Only publish a warm artifact when it cannot skip required hydration."""
    snapshot = source.payload.get("snapshot") or {}
    topology_ref = snapshot.get("topology_ref") if isinstance(snapshot, dict) else None
    profile_id = topology_ref.get("profile_id") if isinstance(topology_ref, dict) else None
    if not profile_id or str(profile_id).upper() == "ALARM_ONLY":
        return True
    topology = source.payload.get("topology") or {}
    return bool(topology.get("edges")) if isinstance(topology, dict) else False


def _is_terminal_quality_row(
    row: Any,
    *,
    expected_config_version: str | None = None,
    expected_review_config_version: str | None = None,
    expected_topology_version: str | None = None,
    topology_version_known: bool = False,
) -> bool:
    return terminal_quality_row_is_current(
        row,
        snapshot_id=getattr(row, "snapshot_id", None),
        snapshot_version=getattr(row, "snapshot_version", None),
        config_version=expected_config_version,
        review_config_version=expected_review_config_version,
        topology_version=expected_topology_version,
        topology_version_known=topology_version_known,
    )


@dataclass(frozen=True)
class _SnapshotSource:
    snapshot_id: str
    snapshot_version: str
    payload: dict[str, Any]
    origin: str

    @property
    def identity(self) -> tuple[str, str]:
        return self.snapshot_id, self.snapshot_version


class SnapshotQualityRunner:
    """Continuously analyze catalog and durable snapshots without UI selection."""

    def __init__(
        self,
        repository,
        coordinator,
        *,
        config_path: Path,
        config_template: Any | None = None,
    ) -> None:
        self.repository = repository
        self.coordinator = coordinator
        self.config_path = config_path
        # Calibration can replace the active config with a generated file
        # while ``_base_config_path`` still points at the startup YAML.  Keep
        # the exact active immutable config for isolated workers so their
        # projections use the same version as the HTTP workspace.
        self.config_template = deepcopy(config_template) if config_template is not None else None
        self.interval_seconds = max(
            1.0, float(os.environ.get("NOCPRO_QUALITY_BACKGROUND_INTERVAL_SECONDS", "4"))
        )
        self.job_poll_seconds = max(
            0.5,
            float(os.environ.get("NOCPRO_QUALITY_BACKGROUND_JOB_POLL_SECONDS", "2")),
        )
        self.timeout_seconds = max(
            60.0,
            float(
                os.environ.get(
                    "NOCPRO_QUALITY_BACKGROUND_TIMEOUT_SECONDS", str(2 * 60 * 60)
                )
            ),
        )
        self.max_workers = max(
            1, int(os.environ.get("NOCPRO_QUALITY_BACKGROUND_WORKERS", "2"))
        )
        self._scheduler_task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()
        self._source_tasks: dict[tuple[str, str], asyncio.Task[Any]] = {}
        self._completed: dict[tuple[str, str], tuple[str | None, str | None]] = {}
        self._ingested: set[tuple[str, str]] = set()
        self._catalog_payloads: dict[tuple[str, str], _SnapshotSource] = {}
        self._catalog_by_item_id: dict[str, _SnapshotSource] = {}
        self._semaphore = asyncio.Semaphore(self.max_workers)
        # Do not use asyncio's implicit default executor here.  The API owns
        # its lifecycle explicitly, and this also keeps snapshot preparation
        # separate from request handlers and Tier-2's per-worker executors.
        self._prepare_executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="nocpro-quality-prepare",
        )

    def start(self) -> None:
        if self._scheduler_task is not None and not self._scheduler_task.done():
            return
        self._stop_event.clear()
        self._scheduler_task = asyncio.create_task(
            self._schedule_loop(), name="snapshot-quality-scheduler"
        )

    async def stop(self) -> None:
        self._stop_event.set()
        scheduler = self._scheduler_task
        if scheduler is not None and not scheduler.done():
            scheduler.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler
        self._scheduler_task = None
        tasks = list(self._source_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._source_tasks.clear()
        self._prepare_executor.shutdown(wait=False, cancel_futures=True)

    async def _schedule_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                active_workspace = getattr(self.coordinator, "workspace", None)
                active_config = (
                    getattr(active_workspace, "config", None)
                    or self.config_template
                )
                config_snapshot = deepcopy(active_config) if active_config is not None else None
                config_version = getattr(config_snapshot, "config_version", None)
                active_topologies: dict[str, str | None] = {}
                active_source_count = sum(
                    not task.done() for task in self._source_tasks.values()
                )
                available_slots = max(0, self.max_workers - active_source_count)
                for source in await self._sources():
                    if available_slots == 0:
                        break
                    raw_snapshot = source.payload.get("snapshot") or {}
                    topo_ref = raw_snapshot.get("topology_ref") or {}
                    source_topology_version = await effective_topology_version(
                        source.snapshot_id,
                        pinned_version=_topology_version(source.payload),
                        explicit_profile=topo_ref.get("profile_id") if isinstance(topo_ref, dict) else None,
                        repository=getattr(self.coordinator, "topology_repository", None),
                        active_by_profile=active_topologies,
                    )
                    version_key = (config_version, source_topology_version)
                    if (
                        source.identity in self._completed
                        and self._completed[source.identity] == version_key
                    ):
                        continue
                    existing = self._source_tasks.get(source.identity)
                    if existing is not None and not existing.done():
                        continue
                    task = asyncio.create_task(
                        self._run_source(source, config_snapshot=config_snapshot),
                        name=f"snapshot-quality:{source.snapshot_id}:{source.snapshot_version}",
                    )
                    available_slots -= 1
                    self._source_tasks[source.identity] = task
                    task.add_done_callback(
                        lambda done, identity=source.identity, version=version_key: self._source_done(
                            identity, version, done
                        )
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Snapshot-wide quality scheduling iteration failed")
            await asyncio.sleep(self.interval_seconds)

    def _source_done(
        self,
        identity: tuple[str, str],
        version_key: tuple[str | None, str | None],
        task: asyncio.Task[Any],
    ) -> None:
        if task.cancelled():
            return
        try:
            result = task.result()
        except Exception:
            LOGGER.exception("Snapshot quality runner failed for %s/%s", *identity)
            return
        if result == "COMPLETE":
            self._completed[identity] = version_key

    async def _sources(self) -> list[_SnapshotSource]:
        sources: dict[tuple[str, str], _SnapshotSource] = dict(self._catalog_payloads)

        # Catalog payloads are loaded independently of the selected UI
        # snapshot.  This is what makes an unopened portfolio card eligible
        # for analysis.
        for item in list_catalog_presets():
            snapshot_id = str(item["snapshot_id"])
            cached_source = self._catalog_by_item_id.get(snapshot_id)
            if cached_source is not None:
                sources[cached_source.identity] = cached_source
                continue
            try:
                # Presets are local immutable JSON files.  Reading them
                # synchronously avoids the executor shutdown behavior of
                # asyncio.to_thread in the API process and keeps this catalog
                # discovery step deterministic; Tier-2 itself remains in the
                # dedicated analysis executors.
                payload, _ = load_preset_payload(snapshot_id)
                raw_snapshot = payload.get("snapshot") or {}
                source = _SnapshotSource(
                    snapshot_id=str(raw_snapshot["snapshot_id"]),
                    snapshot_version=str(raw_snapshot["snapshot_version"]),
                    payload=payload,
                    origin="catalog",
                )
                self._catalog_payloads[source.identity] = source
                self._catalog_by_item_id[snapshot_id] = source
                sources[source.identity] = source
            except Exception as exc:
                LOGGER.warning(
                    "Skipping unavailable catalog snapshot %s in background quality runner: %s",
                    snapshot_id,
                    exc,
                )

        # Also pick up Kafka/direct-ingested snapshots that are not in the
        # static catalog.  READY is deliberately used here: Tier-1A must have
        # established the durable package before the runner consumes it.
        try:
            live_rows = []
            page_size = 200
            offset = 0
            while True:
                page = await self.repository.list_live_snapshots(
                    limit=page_size,
                    offset=offset,
                )
                live_rows.extend(page)
                if len(page) < page_size:
                    break
                offset += page_size
        except Exception:
            LOGGER.debug("Could not list durable snapshots for quality runner", exc_info=True)
            live_rows = []
        for row in live_rows:
            snapshot_id = str(row["snapshot_id"])
            try:
                snapshot_version = str(row["snapshot_version"])
                payload = await self.repository.get_ready_snapshot_payload(
                    snapshot_id,
                    snapshot_version,
                )
                if not isinstance(payload, dict):
                    continue
                raw_snapshot = payload.get("snapshot") or {}
                identity = (
                    str(raw_snapshot["snapshot_id"]),
                    str(raw_snapshot["snapshot_version"]),
                )
                # A Kafka/direct-ingested snapshot may reuse an ID with a
                # newer immutable version than the catalog preset.  Keep the
                # exact identity as the de-duplication key; dropping by ID
                # would leave the background runner on stale evidence.
                if identity in sources:
                    continue
                sources[identity] = _SnapshotSource(
                    snapshot_id=identity[0],
                    snapshot_version=identity[1],
                    payload=payload,
                    origin="durable",
                )
            except Exception as exc:
                LOGGER.warning(
                    "Skipping durable snapshot %s in background quality runner: %s",
                    snapshot_id,
                    exc,
                )
        # Do not let a 500-alarm replay monopolize the only queue slot before
        # the small evolution/reference snapshots get registered and assessed.
        # The scheduler still honours NOCPRO_QUALITY_BACKGROUND_WORKERS, but a
        # deterministic size order gives the portfolio useful progress early.
        return sorted(
            sources.values(),
            key=lambda source: (
                len(source.payload.get("chains") or []),
                source.snapshot_id,
                source.snapshot_version,
            ),
        )

    async def _ensure_durable(self, source: _SnapshotSource) -> bool:
        if source.identity in self._ingested:
            return True
        try:
            await self.repository.ingest_direct(deepcopy(source.payload))
        except Exception as exc:
            # Do not analyze or permanently suppress this source after a
            # transient persistence failure. The scheduler retries it on its
            # next pass; an exact duplicate is returned as success by the
            # repository's idempotent ingest path.
            LOGGER.warning(
                "Background quality could not register snapshot %s/%s (%s): %s",
                source.snapshot_id,
                source.snapshot_version,
                source.origin,
                exc,
            )
            return False
        self._ingested.add(source.identity)
        return True

    async def _run_source(
        self,
        source: _SnapshotSource,
        *,
        config_snapshot: Any | None = None,
    ) -> str:
        async with self._semaphore:
            if not await self._ensure_durable(source):
                return "RETRY"
            worker = Workspace(config_path=self.config_path)
            active_workspace = getattr(self.coordinator, "workspace", None)
            current_config = (
                config_snapshot
                or getattr(active_workspace, "config", None)
                or self.config_template
            )
            if current_config is not None:
                worker.config = deepcopy(current_config)
            worker.attach_persistence(self.repository, self.coordinator)
            try:
                # Keep package state isolated from the active HTTP workspace;
                # listeners persist the exact snapshot identity from this
                # worker's package and never replace what the operator sees.
                loop = asyncio.get_running_loop()
                analysis_payload = deepcopy(source.payload)
                hydrated_package = None
                hydrate_topology = getattr(
                    self.coordinator,
                    "_hydrate_payload_topology_if_needed",
                    None,
                )
                if callable(hydrate_topology):
                    hydrated_package = await hydrate_topology(analysis_payload)
                analysis_source = _SnapshotSource(
                    snapshot_id=source.snapshot_id,
                    snapshot_version=source.snapshot_version,
                    payload=analysis_payload,
                    origin=source.origin,
                )
                await loop.run_in_executor(
                    self._prepare_executor,
                    worker.replace_snapshot,
                    hydrated_package or deepcopy(source.payload),
                )
                if (
                    worker.package is not None
                    and hydrated_package is None
                    and analysis_payload.get("topology") != source.payload.get("topology")
                ):
                    # Compatibility for lightweight mutating hydrator adapters;
                    # production coordinator returns a validated runtime package.
                    worker.package.topology = deepcopy(analysis_payload["topology"])
                # Publish only the exact immutable Tier-1A state.  The active
                # HTTP workspace validates payload/config/topology identity
                # again before promotion; a background worker never swaps the
                # operator's current snapshot directly.
                active_workspace = getattr(self.coordinator, "workspace", None)
                if (
                    active_workspace is not None
                    and worker.package is not None
                    and worker.precompute is not None
                    and hasattr(active_workspace, "store_prepared_activation")
                    and _source_activation_topology_is_complete(analysis_source)
                ):
                    active_workspace.store_prepared_activation(
                        source.payload,
                        worker.package,
                        worker.precompute,
                        config_version=worker.config.config_version,
                    )
                elif not _source_activation_topology_is_complete(analysis_source):
                    LOGGER.debug(
                        "Skipped warm activation for %s/%s until required topology edges are present",
                        source.snapshot_id,
                        source.snapshot_version,
                    )

                # A completed quality row still needs a warm activation
                # artifact.  Without this small preparation pass, the first
                # click on an already-processed portfolio card falls through
                # to the synchronous cold activation path and looks like the
                # background evaluator has stopped.  No Deep Dive or LLM work
                # is started in this branch.
                if await self._source_quality_complete(
                    analysis_source,
                    expected_config_version=worker.config.config_version,
                ):
                    LOGGER.info(
                        "Background quality already complete; activation warmed for snapshot %s/%s",
                        source.snapshot_id,
                        source.snapshot_version,
                    )
                    return "COMPLETE"

                await worker.resume_snapshot_quality()
                deadline = asyncio.get_running_loop().time() + self.timeout_seconds
                while not self._stop_event.is_set():
                    await worker.flush_deep_dive_persistence()
                    await worker.flush_review_persistence()
                    if await self._quality_complete(worker):
                        LOGGER.info(
                            "Background deterministic quality complete for snapshot %s/%s",
                            source.snapshot_id,
                            source.snapshot_version,
                        )
                        return "COMPLETE"
                    if asyncio.get_running_loop().time() >= deadline:
                        LOGGER.warning(
                            "Background deterministic quality timed out for snapshot %s/%s; unresolved chains will be retried on the next scheduler pass",
                            source.snapshot_id,
                            source.snapshot_version,
                        )
                        return "TIMEOUT"
                    await asyncio.sleep(self.job_poll_seconds)
                    await worker.resume_snapshot_quality()
                return "STOPPED"
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "Background deterministic quality failed for snapshot %s/%s",
                    source.snapshot_id,
                    source.snapshot_version,
                )
                return "FAILED"
            finally:
                with suppress(Exception):
                    await worker.flush_deep_dive_persistence()
                with suppress(Exception):
                    await worker.flush_review_persistence()
                worker.close()

    async def _source_quality_complete(
        self,
        source: _SnapshotSource,
        *,
        expected_config_version: str | None = None,
    ) -> bool:
        """Avoid rebuilding Tier-1A for an immutable source already evaluated."""
        raw_chains = source.payload.get("chains") or []
        eligible_ids = {
            str(chain.get("chain_id"))
            for chain in raw_chains
            if isinstance(chain, dict)
            and int(chain.get("member_count") or 0) > 1
        }
        if not eligible_ids:
            return True
        if expected_config_version is None:
            expected_config_version = getattr(
                getattr(getattr(self.coordinator, "workspace", None), "config", None),
                "config_version",
                None,
            )
        config = self.config_template or getattr(
            getattr(self.coordinator, "workspace", None), "config", None
        )
        expected_review_config_version = (
            config.counterfactual.config_version
            if config is not None and config.counterfactual is not None
            else "UNAVAILABLE"
        )
        try:
            assessments = await self.repository.list_chain_quality_assessments(
                snapshot_id=source.snapshot_id,
                snapshot_version=source.snapshot_version,
            )
        except Exception:
            return False
        snapshot = source.payload.get("snapshot") or {}
        topo_ref = snapshot.get("topology_ref") if isinstance(snapshot, dict) else None
        topology_version = _topology_version(source.payload)
        topology_known = snapshot_topology_profile(
            source.snapshot_id,
            topo_ref.get("profile_id") if isinstance(topo_ref, dict) else None,
        ) is not None
        completed_ids = {
            str(row.chain_id)
            for row in assessments
            if _is_terminal_quality_row(
                row,
                expected_config_version=expected_config_version,
                expected_review_config_version=expected_review_config_version,
                expected_topology_version=topology_version,
                topology_version_known=topology_known,
            )
        }
        return eligible_ids.issubset(completed_ids)

    async def _quality_complete(self, worker: Workspace) -> bool:
        package = worker.package
        if package is None:
            return False
        eligible_ids = {
            str(chain_id)
            for chain_id in package.chains
            if len(package.members_of(chain_id)) > 1
        }
        if not eligible_ids:
            return True
        try:
            assessments = await self.repository.list_chain_quality_assessments(
                snapshot_id=package.snapshot.snapshot_id,
                snapshot_version=package.snapshot.snapshot_version,
            )
        except Exception:
            return False
        expected_config_version = worker.config.config_version
        expected_review_config_version = (
            worker.config.counterfactual.config_version
            if worker.config.counterfactual is not None
            else "UNAVAILABLE"
        )
        topology_version = _topology_version(package)
        topology_known = snapshot_topology_profile(
            package.snapshot.snapshot_id,
            getattr(getattr(package.snapshot, "topology_ref", None), "profile_id", None),
        ) is not None
        completed_ids = {
            str(row.chain_id)
            for row in assessments
            if _is_terminal_quality_row(
                row,
                expected_config_version=expected_config_version,
                expected_review_config_version=expected_review_config_version,
                expected_topology_version=topology_version,
                topology_version_known=topology_known,
            )
        }
        return eligible_ids.issubset(completed_ids)
