"""Command-line entry point.

Subcommands:
  profile   report the observed profile of a real export
  replay    emit a Direct Snapshot package from the real alarm export
  golden    emit the Golden 2214039 snapshot package
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .config import load_config
from .contract import ContractViolation
from .fixtures.golden import load_golden_fixture
from .loaders.alarm_csv import AlarmCsvLoader
from .loaders.topology_ip_csv import TopoIPLoader
from .producer.direct_snapshot import DirectSnapshotProducer
from .producer.kafka_snapshot import KafkaSnapshotConfig, publish_snapshot
from .replay.snapshot import build_golden_snapshot, build_real_replay_snapshot

DEFAULT_ALARM_CSV = "datasets/raw/alarm_data.csv"
DEFAULT_TOPO_IP_CSV = "datasets/raw/topoIP-8zjkidh613ffzdck7jca5j6bdc.csv"
DEFAULT_SYNTHETIC_DIR = "docs/examples/synthetic"


def _cmd_profile(args: argparse.Namespace) -> int:
    if args.source == "alarm":
        prof = AlarmCsvLoader(args.path).profile()
        print(f"file:                  {prof.file_path}")
        print(f"records:               {prof.record_count}")
        print(f"columns:               {prof.column_count}")
        print(f"unique chaining_id:    {prof.unique_chaining_ids}")
        print(
            f"singleton chains:      {prof.singleton_chains} "
            f"({prof.singleton_pct:.4f}%)"
        )
        print(f"max chain size:        {prof.max_chain_size} ({prof.max_chain_id})")
        print(f"unique device_code:    {prof.unique_device_codes}")
        print(f"node_reference filled: {prof.node_reference_fill_pct:.4f}%")
        for flag, count in sorted(prof.flag_counts.items()):
            print(f"  flag {flag}: {count}")
    else:
        prof = TopoIPLoader(args.path).profile()
        print(f"file:              {prof.file_path}")
        print(f"rows:              {prof.row_count}")
        print(f"columns:           {prof.column_count}")
        print(f"unique devices:    {prof.unique_devices}")
        print(f"with update_time:  {prof.rows_with_update_time}")
        print(f"SITE_ROUTER src:   {prof.source_class_pct('SITE_ROUTER'):.4f}%")
    return 0


def _emit(package, args: argparse.Namespace) -> int:
    producer = DirectSnapshotProducer()
    try:
        if args.out:
            target = producer.write(package, args.out)
            print(f"wrote {target}")
        if args.kafka_bootstrap:
            batch = asyncio.run(
                publish_snapshot(
                    package,
                    bootstrap_servers=args.kafka_bootstrap,
                    config=KafkaSnapshotConfig(
                        topic=args.kafka_topic,
                        chunk_target_bytes=args.chunk_target_bytes,
                    ),
                )
            )
            print(
                f"published snapshot={package.snapshot.snapshot_id} "
                f"version={package.snapshot.snapshot_version} "
                f"chunks={len(batch.chunks)} topic={args.kafka_topic}"
            )
        elif not args.out:
            print(producer.render(package))
    except ContractViolation as exc:
        print(f"contract validation failed:\n{exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    package = build_real_replay_snapshot(
        alarm_csv_path=args.alarm_csv,
        config=config,
        snapshot_id=args.snapshot_id,
        snapshot_version=args.snapshot_version,
        topo_ip_path=args.topo_ip if args.with_topology else None,
        chain_ids=set(args.chain_id) if args.chain_id else None,
        limit=args.limit,
    )
    return _emit(package, args)


def _cmd_golden(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    device_codes: set[str] = set()
    if args.with_topology and Path(args.topo_ip).is_file():
        device_codes = TopoIPLoader(args.topo_ip).device_codes()
    package = build_golden_snapshot(
        config=config,
        fixture=load_golden_fixture(args.fixture_dir),
        topo_ip_device_codes=device_codes,
        snapshot_version=args.snapshot_version,
    )
    return _emit(package, args)


def _cmd_build_sequences(args: argparse.Namespace) -> int:
    """Materialize the shipped sequence fixtures next to their manifests."""
    from .config import GENERATOR_VERSION
    from .scenarios import (
        COUNTERFACTUAL_FIXTURES,
        SEQUENCE_FIXTURES,
        build_synthetic_snapshot,
        generate_integrated_topology,
        load_scenario,
    )
    from .scenarios.sequence import load_sequence_manifest

    base = Path(args.base_dir)
    producer = DirectSnapshotProducer()
    written = 0

    for fixture in SEQUENCE_FIXTURES:
        directory = base / fixture.directory
        manifest = load_sequence_manifest(directory / "sequence.yaml")
        if len(manifest.snapshots) != len(fixture.snapshots):
            print(
                f"{fixture.scenario_id}: manifest lists {len(manifest.snapshots)} "
                f"snapshots but fixture defines {len(fixture.snapshots)}",
                file=sys.stderr,
            )
            return 2

        for index, (name, chains) in enumerate(
            zip(manifest.snapshots, fixture.snapshots)
        ):
            generator_version = fixture.generator_version or GENERATOR_VERSION
            topology = None
            topology_source = None
            if fixture.topology_scenario_file:
                scenario = load_scenario(
                    directory / fixture.topology_scenario_file
                )
                if scenario.scenario_id != fixture.scenario_id:
                    print(
                        f"{fixture.scenario_id}: topology scenario declares "
                        f"{scenario.scenario_id!r}",
                        file=sys.stderr,
                    )
                    return 2
                alarm_ids = tuple(
                    dict.fromkeys(
                        alarm_id
                        for members in chains.values()
                        for alarm_id in members
                    )
                )
                topology = generate_integrated_topology(
                    scenario,
                    generator_version=generator_version,
                    alarm_resource_ids=alarm_ids,
                )
                topology_source = scenario.topology_source
            package = build_synthetic_snapshot(
                scenario_id=fixture.scenario_id,
                seed=manifest.seed,
                generator_version=generator_version,
                snapshot_index=index,
                chains=chains,
                alarm_families=fixture.alarm_families,
                alarm_profiles=fixture.alarm_profiles,
                generation_rule=(
                    f"{manifest.sequence_type.value} sequence member {index}"
                ),
                topology=topology,
                topology_source=topology_source,
            )
            try:
                producer.write(package, directory / name)
            except ContractViolation as exc:
                print(f"{name}: {exc}", file=sys.stderr)
                return 2
            written += 1
        print(f"{fixture.scenario_id}: wrote {len(fixture.snapshots)} snapshots")

    for fixture in COUNTERFACTUAL_FIXTURES:
        directory = base / fixture.directory
        package = build_synthetic_snapshot(
            scenario_id=fixture.scenario_id,
            seed=42,
            generator_version=GENERATOR_VERSION,
            snapshot_index=0,
            chains=fixture.snapshot_chains(),
            alarm_profiles=fixture.alarm_profiles,
            generation_rule=f"COUNTERFACTUAL {fixture.mutation} fixture",
        )
        try:
            producer.write(package, directory / "snapshot_000.json")
        except ContractViolation as exc:
            print(f"{fixture.scenario_id}: {exc}", file=sys.stderr)
            return 2
        written += 1
        print(f"{fixture.scenario_id}: wrote snapshot_000.json")

    print(f"total {written} snapshot file(s)")
    return 0


def _cmd_run_sequence(args: argparse.Namespace) -> int:
    from .replay import SequenceRunner, validate_sequence_payloads

    errors = validate_sequence_payloads(args.directory)
    if errors:
        for message in errors:
            print(f"invalid: {message}", file=sys.stderr)
        return 2

    runner = SequenceRunner(args.directory)
    manifest = runner.manifest
    print(f"scenario:      {manifest.scenario_id}")
    print(f"sequence_type: {manifest.sequence_type.value}")
    if manifest.history_until_exclusive:
        print(f"history:       {list(manifest.history_snapshots)}")
        print(f"target:        {manifest.target_snapshot}")
    for transition in manifest.expected_transitions:
        print(
            f"transition:    {transition.from_snapshot} -> "
            f"{transition.to_snapshot} = {transition.expected_event.value}"
        )
    for step in runner.run():
        role = "history" if step.is_history else ("target" if step.is_target else "-")
        chains = len(step.payload.get("chains") or [])
        alarms = len(step.payload.get("alarms") or [])
        print(
            f"step {step.index}: {step.name} role={role} chains={chains} alarms={alarms}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nocpro-mock")
    parser.add_argument("--config", default=None, help="path to mock capability config")
    sub = parser.add_subparsers(dest="command", required=True)

    p_profile = sub.add_parser("profile", help="profile a real export")
    p_profile.add_argument("source", choices=["alarm", "topoip"])
    p_profile.add_argument("path")
    p_profile.set_defaults(func=_cmd_profile)

    p_replay = sub.add_parser("replay", help="emit a Direct Snapshot package")
    p_replay.add_argument("--alarm-csv", default=DEFAULT_ALARM_CSV)
    p_replay.add_argument("--topo-ip", default=DEFAULT_TOPO_IP_CSV)
    p_replay.add_argument("--with-topology", action="store_true")
    p_replay.add_argument("--snapshot-id", default="snapshot_replay_001")
    p_replay.add_argument(
        "--snapshot-version",
        default="1",
        help="explicit logical version used for transport and persistence identity",
    )
    p_replay.add_argument("--chain-id", action="append", default=[])
    p_replay.add_argument("--limit", type=int, default=None)
    p_replay.add_argument("--out", default=None)
    _add_kafka_options(p_replay)
    p_replay.set_defaults(func=_cmd_replay)

    p_golden = sub.add_parser("golden", help="emit the Golden 2214039 package")
    p_golden.add_argument("--fixture-dir", default=None)
    p_golden.add_argument("--topo-ip", default=DEFAULT_TOPO_IP_CSV)
    p_golden.add_argument("--with-topology", action="store_true")
    p_golden.add_argument("--snapshot-version", default="1")
    p_golden.add_argument("--out", default=None)
    _add_kafka_options(p_golden)
    p_golden.set_defaults(func=_cmd_golden)

    p_build = sub.add_parser(
        "build-sequences", help="materialize the shipped sequence fixtures"
    )
    p_build.add_argument("--base-dir", default=DEFAULT_SYNTHETIC_DIR)
    p_build.set_defaults(func=_cmd_build_sequences)

    p_run = sub.add_parser("run-sequence", help="step through a snapshot sequence")
    p_run.add_argument("directory")
    p_run.set_defaults(func=_cmd_run_sequence)

    return parser


def _add_kafka_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--kafka-bootstrap",
        default=None,
        help="publish chunked snapshot events instead of printing JSON",
    )
    parser.add_argument("--kafka-topic", default="nocpro.snapshot.v1")
    parser.add_argument("--chunk-target-bytes", type=int, default=2 * 1024 * 1024)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
