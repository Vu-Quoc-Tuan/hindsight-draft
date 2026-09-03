"""Mutation Webhook Dispatcher.

Dispatches approved chain mutation decisions (e.g. SPLIT, REMOVE, MOVE, MERGE)
to an upstream NocPro callback/webhook endpoint or audit log.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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

    If webhook_url is None or empty, the event is recorded locally in structured
    audit logs without making an external network call.
    """
    payload = asdict(event)

    if not webhook_url:
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
        webhook_url,
        data=raw_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "nocpro-chain-explain/mutation-dispatcher",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return {
                "dispatched": True,
                "status_code": response.status,
                "event_id": event.event_id,
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
        logger.warning("Failed to dispatch mutation webhook to %s: %s", webhook_url, exc)
        return {
            "dispatched": False,
            "error": str(exc),
            "event_id": event.event_id,
        }
