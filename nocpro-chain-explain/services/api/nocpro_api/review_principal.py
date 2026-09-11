from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import ipaddress
import os
from pathlib import Path
from typing import Any, Sequence
import yaml
from fastapi import HTTPException, Request, status


class ReviewIdentityMode(str, Enum):
    DISABLED = "DISABLED"
    LOCAL_DEV = "LOCAL_DEV"
    TRUSTED_PROXY = "TRUSTED_PROXY"


DEFAULT_TRUSTED_CIDRS = (
    "127.0.0.1/32",
    "::1/128",
)


from review_learning.contracts import AUTHORIZED_FEEDBACK_ROLES, AUTHORIZED_PO_ROLES


class ReviewReasonPolicyUnavailable(RuntimeError):
    """Raised when the server cannot load a valid active review-reason policy."""


@dataclass(frozen=True)
class ReviewerPrincipal:
    """Authenticated human or service reviewer identity derived strictly by the server."""

    subject: str
    role: str
    domain_scope: tuple[str, ...]
    auth_type: str
    client_ip: str | None = None
    roles: tuple[str, ...] = ()

    @property
    def all_roles(self) -> frozenset[str]:
        res = set(r.strip().upper() for r in self.roles if r and r.strip())
        if self.role and self.role.strip():
            res.add(self.role.strip().upper())
        return frozenset(res)

    def is_role_authorized_for_po_asserted(self) -> bool:
        return bool(self.all_roles & AUTHORIZED_PO_ROLES)

    def is_role_authorized_for_feedback(self) -> bool:
        return bool(self.all_roles & AUTHORIZED_FEEDBACK_ROLES)

    def verify_domain_authorization(self, required_domain: str | None) -> None:
        verify_domain_authorization(self, required_domain)

    def is_domain_authorized(self, required_domain: str | None) -> bool:
        try:
            self.verify_domain_authorization(required_domain)
            return True
        except Exception:
            return False

    @property
    def is_read_only(self) -> bool:
        return self.role.upper().strip() in {"READONLY", "READONLY_OPERATOR", "VIEWER", "AUDITOR"}

    @property
    def can_assert_po_truth(self) -> bool:
        return self.role.upper().strip() in {"PRODUCT_OWNER", "PRINCIPAL_OPERATOR"}


def get_configured_identity_mode() -> ReviewIdentityMode:
    raw = os.environ.get("REVIEW_IDENTITY_MODE", "").strip().upper()
    app_env = os.environ.get("APP_ENV", "").strip().lower()
    env = os.environ.get("ENVIRONMENT", "development").strip().lower()
    is_prod = app_env in {"prod", "production"} or env in {"prod", "production"}

    if raw:
        try:
            mode = ReviewIdentityMode(raw)
            if mode == ReviewIdentityMode.LOCAL_DEV and is_prod:
                return ReviewIdentityMode.DISABLED
            return mode
        except ValueError:
            pass
    # In production, default fail-closed to DISABLED. In dev/test, default to LOCAL_DEV.
    if is_prod:
        return ReviewIdentityMode.DISABLED
    return ReviewIdentityMode.LOCAL_DEV


def _is_trusted_ip(client_ip: str | None, trusted_cidrs: Sequence[str]) -> bool:
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for cidr in trusted_cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def verify_domain_authorization(principal: ReviewerPrincipal, required_domain: str | None) -> None:
    """Authorize reviewer against target incident domain."""
    from review_learning.contracts import ReviewDomainForbidden
    if not required_domain or str(required_domain).upper().strip() in {"", "NONE"}:
        required_domain = "UNKNOWN_DOMAIN"
    domain_clean = str(required_domain).upper().strip()
    if domain_clean == "UNKNOWN_DOMAIN":
        if not any(d.upper() == "UNKNOWN_DOMAIN" or d == "*" for d in principal.domain_scope):
            raise ReviewDomainForbidden(
                f"Reviewer principal {principal.subject!r} with domain scope {principal.domain_scope} is not authorized for UNKNOWN_DOMAIN"
            )
        return
    if not any(d.upper() == domain_clean or d == "*" for d in principal.domain_scope):
        raise ReviewDomainForbidden(
            f"Reviewer principal {principal.subject!r} with domain scope {principal.domain_scope} is not authorized for review domain {required_domain!r}"
        )


def get_reviewer_principal(request: Request) -> ReviewerPrincipal:
    """FastAPI dependency to extract server-derived reviewer identity.

    The client-submitted operator_id in request payloads is NEVER accepted as authority.
    """
    mode = get_configured_identity_mode()
    client_ip = request.client.host if request.client else None

    if mode == ReviewIdentityMode.DISABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Review identity provider is DISABLED; operator feedback service unavailable.",
        )

    if mode == ReviewIdentityMode.LOCAL_DEV:
        is_prod = (
            os.environ.get("APP_ENV", "").strip().lower() in {"prod", "production"}
            or os.environ.get("ENVIRONMENT", "").strip().lower() in {"prod", "production"}
        )
        if is_prod:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LOCAL_DEV identity mode is forbidden in production environment.",
            )

        allow_test_override = (
            os.environ.get("REVIEW_TEST_IDENTITY_OVERRIDE", "").strip() == "1"
            and not is_prod
        )

        if allow_test_override and request.headers.get("X-Dev-Operator-Id"):
            subject = request.headers["X-Dev-Operator-Id"]
            scope_header = request.headers.get("X-Dev-Domain-Scope")
            domain_scope = (
                tuple(s.strip() for s in scope_header.split(",") if s.strip())
                if scope_header
                else ("*",)
            )
        else:
            subject = (
                os.environ.get("REVIEW_LOCAL_SUBJECT")
                or os.environ.get("LOCAL_DEV_OPERATOR_ID")
                or "local_dev_operator"
            )
            scope_env = (
                os.environ.get("REVIEW_LOCAL_DOMAIN_SCOPE")
                or os.environ.get("LOCAL_DEV_DOMAIN_SCOPE")
            )
            if scope_env:
                domain_scope = tuple(s.strip() for s in scope_env.split(",") if s.strip())
            else:
                domain_scope = ("*",)

        return ReviewerPrincipal(
            subject=subject,
            role="PRODUCT_OWNER",
            domain_scope=domain_scope,
            auth_type="LOCAL_DEV",
            client_ip=client_ip,
            roles=("PRODUCT_OWNER",),
        )

    if mode == ReviewIdentityMode.TRUSTED_PROXY:
        is_prod = (
            os.environ.get("APP_ENV", "").strip().lower() in {"prod", "production"}
            or os.environ.get("ENVIRONMENT", "").strip().lower() in {"prod", "production"}
        )
        cidrs_str = os.environ.get("TRUSTED_PROXY_CIDRS", "")
        trusted_cidrs = (
            [c.strip() for c in cidrs_str.split(",") if c.strip()]
            if cidrs_str
            else list(DEFAULT_TRUSTED_CIDRS)
        )

        if not _is_trusted_ip(client_ip, trusted_cidrs):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Untrusted proxy source: {client_ip}",
            )

        subject = (
            request.headers.get("X-Forwarded-User")
            or request.headers.get("X-Remote-User")
            or request.headers.get("X-Forwarded-Preferred-Username")
        )
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing identity header from trusted reverse proxy",
            )

        raw_roles = request.headers.get("X-User-Roles")
        scope_header = request.headers.get("X-Domain-Scope")

        if is_prod:
            if not raw_roles or not raw_roles.strip():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing required X-User-Roles header in production environment",
                )
            if not scope_header or not scope_header.strip():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Missing required X-Domain-Scope header in production environment",
                )
            parsed_roles = tuple(r.strip().upper() for r in raw_roles.split(",") if r.strip())
            domain_scope = tuple(s.strip() for s in scope_header.split(",") if s.strip())
        else:
            if raw_roles and raw_roles.strip():
                parsed_roles = tuple(r.strip().upper() for r in raw_roles.split(",") if r.strip())
            else:
                parsed_roles = ("OPERATOR",)
            if scope_header and scope_header.strip():
                domain_scope = tuple(s.strip() for s in scope_header.split(",") if s.strip())
            else:
                domain_scope = ("IP_NETWORK", "IT_SERVICES")

        if not parsed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing valid roles in X-User-Roles header",
            )

        po_matches = [r for r in parsed_roles if r in AUTHORIZED_PO_ROLES]
        canonical_role = po_matches[0] if po_matches else parsed_roles[0]

        return ReviewerPrincipal(
            subject=subject,
            role=canonical_role,
            domain_scope=domain_scope,
            auth_type="TRUSTED_PROXY",
            client_ip=client_ip,
            roles=parsed_roles,
        )

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unknown review identity mode: {mode}",
    )


DEFAULT_REASONS_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "review-learning" / "review-reasons-v1.yaml"
)


def load_reason_policy(policy_path: Path | None = None) -> dict[str, Any]:
    path = policy_path or DEFAULT_REASONS_PATH
    if not path.exists():
        raise ReviewReasonPolicyUnavailable(f"Active review reason policy not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            policy = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ReviewReasonPolicyUnavailable(f"Active review reason policy is invalid YAML: {path}") from exc
    if not isinstance(policy, dict):
        raise ReviewReasonPolicyUnavailable("Active review reason policy must be a mapping")
    version = policy.get("policy_version")
    decisions = policy.get("reasons_by_decision")
    if not isinstance(version, str) or not version.strip():
        raise ReviewReasonPolicyUnavailable("Active review reason policy is missing policy_version")
    if not isinstance(decisions, dict):
        raise ReviewReasonPolicyUnavailable("Active review reason policy requires a reasons_by_decision mapping")
    for decision, reasons in decisions.items():
        if not isinstance(decision, str) or not isinstance(reasons, list):
            raise ReviewReasonPolicyUnavailable("Active review reason policy has an invalid decision entry")
        if any(not isinstance(reason, dict) or not str(reason.get("code", "")).strip() for reason in reasons):
            raise ReviewReasonPolicyUnavailable("Active review reason policy has a reason without a code")
    return policy
