# ADR-0028: Freeze membership Fit, three-axis roles, and WEAK vs INSUFFICIENT DATA semantics

- **Status:** Accepted — frozen by V2.3.1
- **Date:** 2026-08-28
- **Scope:** Member explanation / role semantics

## Context

A low scalar score is not enough to call an alarm WEAK. Missing evidence must be distinguished from evidence that is available but neutral/non-supporting. The final spec defines pair/channel Fit, group Fit, MembershipSupport and a three-axis role model.

## Decision

For channel k:

`D_k(x,C) = {y in C\{x}: availability_k(x,y)=1}`

`Fit_k(x,C) = supported_available_neighbors / |D_k|`, with `|D_k|=0 => ⊥`.

Group Fit:

`Fit_g(x,C)=max(Fit_k)` across computable channels in the derivation group.

Role-eligible groups:

`G_role(x,C) = {g: role_eligible and Fit_g != ⊥}`.

MembershipSupport is the mean Fit_g over `G_role`.

The membership role gate SHALL require:
- `AvailabilityCoverage >= c_min`,
- at least **2 distinct computable ROLE_ELIGIBLE derivation groups**,
- unavailable (`⊥`) is not silently converted to NEUTRAL.

If the gate fails => `INSUFFICIENT_DATA`.

If the gate passes:
- CORE follows the frozen absolute floor + rank/representativeness/positive contrastive margin rules.
- WEAK follows bottom-band + non-positive margin rules.
- otherwise PERIPHERAL.

Structural role and redundancy role are separate axes:
- CONNECTOR/NON_CONNECTOR.
- NEAR_DUPLICATE_CANDIDATE/UNIQUE.

## Rationale

This prevents “few data => weak” and keeps membership, structure and redundancy semantically distinct.

## Consequences

**Positive:** interpretable member WHY and correct insufficient-data handling.

**Trade-offs:** UI/API must expose vector evidence and gate reasons, not only one score.

## Alternatives considered

1. One scalar role score — rejected.
2. Treat unavailable as zero support — rejected.
3. Use system facts/history to strengthen role by default — rejected by eligibility.

## Implementation implications

Store/return enough per-group Fit to explain the scalar. For |C|<8, use the small-chain policy from the spec instead of quantile ranking.

## Invariants / required tests

- Temporal available + all other role groups unavailable => INSUFFICIENT_DATA, not WEAK.
- Two computable neutral groups may satisfy the computability gate and can support a WEAK decision if the other conditions hold.
- SYSTEM_FACT and BEHAVIORAL groups do not enter default MembershipSupport.
- Membership/Structural/Redundancy labels can change independently.

## References

V2.3.1 section 4B and evaluation section 13.
