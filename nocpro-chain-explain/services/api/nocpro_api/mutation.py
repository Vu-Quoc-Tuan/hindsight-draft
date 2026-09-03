"""Mutation Dispatcher for NocPro Chain Explanations.

Dispatches approved chain mutation decisions (e.g. SPLIT, REMOVE, MOVE, MERGE)
to an upstream Viettel NocPro callback/webhook endpoint or audit log.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MutationEvent:
    event_id: str
    chain_id: str
    operation: str
    candidate_id: str
    partition_delta: dict[str, Any]
    operator_id: str
    approved_at: str
    event_type: str = "NOCPRO_CHAIN_MUTATION_APPROVED"
    reason: str | None = None


def dispatch_mutation(
    event: MutationEvent,
    webhook_url: str | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Dispatch an approved mutation event to a configured webhook endpoint.

    If webhook_url is None or empty, falls back to the NOCPRO_MUTATION_WEBHOOK_URL
    environment variable. If still unconfigured, the event is safely recorded
    locally in structured audit logs without failing closed.
    """
    target_url = webhook_url or os.environ.get("NOCPRO_MUTATION_WEBHOOK_URL")
    payload = asdict(event)

    if not target_url:
        logger.info(
            "Recorded approved mutation audit event (no webhook URL configured): %s",
            event.event_id,
        )
        return {
            "dispatched": False,
            "reason": "WEBHOOK_NOT_CONFIGURED",
            "event_id": event.event_id,
            "payload": payload,
        }

    raw_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        target_url,
        data=raw_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "nocpro-chain-explain/mutation-dispatcher",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            resp_body = response.read().decode("utf-8")
            resp_data = None
            try:
                resp_data = json.loads(resp_body)
            except Exception:
                resp_data = {"raw": resp_body}
            return {
                "dispatched": True,
                "status_code": response.status,
                "event_id": event.event_id,
                "response": resp_data,
            }
    except urllib.error.HTTPError as exc:
        logger.warning("Mutation webhook returned HTTP %d: %s", exc.code, exc.reason)
        return {
            "dispatched": False,
            "status_code": exc.code,
            "error": str(exc),
            "event_id": event.event_id,
        }
    except Exception as exc:
        logger.warning("Failed to dispatch mutation webhook to %s: %s", target_url, exc)
        return {
            "dispatched": False,
            "error": str(exc),
            "event_id": event.event_id,
        }
