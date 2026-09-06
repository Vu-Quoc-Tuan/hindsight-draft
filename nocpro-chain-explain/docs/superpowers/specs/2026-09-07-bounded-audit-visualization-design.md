# Bounded Persisted Audit Visualization Design

## Status

Approved for implementation on 2026-09-07.

## Goal

Expose a deterministic, bounded, persisted visualization projection of the
exact Tier-2 Audit graph so operators can inspect graph structure and the best
cut without fabricating nodes, edges, weights, or layout data.

## Non-goals and semantic boundary

The projection is `VISUALIZATION` data only. It must never become an input to:

- the exact Audit verdict or conductance calculation;
- structural roles or MembershipSupport;
- Counterfactual candidate generation or evaluation;
- topology dependency/RCA semantics;
- any fallback approximation of an unavailable exact Audit.

The exact `AuditGraph` remains the sole graph used by Tier-2 structural logic.
Pruning or changing the visualization projection must not change any Audit or
Review result. No GET request may rebuild pair evidence or rerun Tier-2.

## Architecture

Tier-2 already materializes an exact `AuditGraph` for an eligible chain. After
all exact computations finish, the worker derives an immutable bounded
`AuditVisualization` from that graph and the frozen best cut. This projection
is attached to a new `review-audit-v2` artifact and persisted in the existing
insert-only `audit_artifact` record. No new database table or migration is
required.

The artifact reader remains backward-compatible with `review-audit-v1`.
Version 1 artifacts hydrate with visualization status `UNAVAILABLE` and reason
`BOUNDED_PUBLIC_AUDIT_GRAPH_ARTIFACT_NOT_AVAILABLE`; they are never upgraded or
mutated in place.

A dedicated read-only API retrieves the latest compatible persisted Audit
artifact for the active snapshot, version, chain membership, analysis version,
and config version. It returns only the visualization projection and its
identity/provenance. In-memory job responses expose the same typed projection,
so live and persisted paths share one serializer and schema.

## Projection contract

The projection version is `audit-visualization-v1`. Its fixed presentation
bounds are:

```text
max_nodes = 80
max_edges = 160
```

These bounds are visualization policy, not evidence thresholds. They are
included in the projection payload and artifact fingerprint.

### Nodes

Each node contains:

```text
alarm_id
weighted_degree
cut_side = A | B | NONE
structural_role
```

`cut_side` is derived only from the exact best cut. `A` is the best-cut member
set and `B` is its complement. If no exact best cut exists, every node uses
`NONE`. `structural_role` is copied from the exact Tier-2 result when present;
it is not recomputed from the bounded graph.

### Edges

Each edge contains:

```text
source_alarm_id
target_alarm_id
weight
supporting_groups[]
crosses_best_cut
```

Endpoint order is canonical lexical order. Supporting groups are sorted and
deduplicated. `crosses_best_cut` is true only when an exact best cut exists and
the endpoints are on opposing sides.

### Metadata

The projection also records:

```text
status
reason
projection_version
selection_strategy
max_nodes
max_edges
total_node_count
shown_node_count
hidden_node_count
total_edge_count
shown_edge_count
hidden_edge_count
truncated
audit_artifact_id
audit_artifact_fingerprint
```

Counts describe the exact graph versus the bounded projection. The public copy
must label the result as visualization-only and must not call it a complete
graph when `truncated=true`.

## Deterministic selection

For graphs within both caps, all nodes and edges are retained.

For a graph exceeding the node cap:

1. Compute exact weighted degree from the already-built exact graph.
2. If a best cut exists and both sides are non-empty, reserve 40 node slots for
   each side. Within each side, sort by descending weighted degree and then
   ascending alarm ID. If one side has fewer than 40 nodes, give its unused
   slots to the other side using the same ordering.
3. Without a best cut, select the first 80 nodes by descending weighted degree
   and ascending alarm ID.

After node selection, retain only exact edges whose endpoints are selected.
Sort them by descending weight, then ascending canonical endpoint pair, and
keep at most 160. The projection never creates replacement edges, supernodes,
or inferred connectivity.

All output collections are emitted in canonical order so rebuilding from the
same exact inputs produces byte-equivalent semantic payloads and fingerprints.

## Availability and failures

The visualization is `AVAILABLE` only when an exact Tier-2 graph exists and a
versioned projection was persisted or is present in the completed job result.

It is `UNAVAILABLE` with an explicit reason when:

- no compatible persisted Audit artifact exists;
- Tier-2 Audit has not completed;
- Audit is unavailable because its exact execution limit was exceeded;
- a legacy v1 artifact has no projection;
- artifact identity or fingerprint validation fails.

Unavailable is never serialized as an empty available graph. An exact graph
with zero edges is still available and contains its selected nodes with an
empty edge list.

## API and restart behavior

The API adds a read-only endpoint under the selected chain for Audit
visualization. The response carries snapshot, version, chain, artifact, and
projection identities. A context mismatch fails closed.

The live completed-job projection and the response after API/repository restart
must be equal for all semantic fields. Hydration must not refit, rerun, or
reselect the graph.

## UI

The Structural Audit screen replaces the current unavailable placeholder only
when the typed projection is available. It renders a deterministic two-region
SVG:

- best-cut side A on the left and side B on the right;
- nodes ordered by weighted degree and alarm ID;
- within-side edges subdued;
- cross-cut edges emphasized;
- node role and alarm identity available through labels/tooltips;
- a compact legend and shown/hidden counts;
- an explicit `Visualization only` notice.

When no best cut exists, nodes use a deterministic grid projection rather than
inventing partitions. Pixel coordinates are computed only by React and are not
persisted or returned by the backend. The SVG must remain readable at desktop
width and horizontally contained at a 390-pixel viewport.

## Verification

Tests must prove:

- small projections retain all exact nodes and edges;
- 80/160 caps are enforced deterministically;
- best-cut sides receive balanced representation;
- selection is stable under input iteration reordering;
- no edge or node is fabricated;
- projection changes cannot alter Audit verdict, conductance, roles, or Review;
- v1 artifact hydration yields explicit unavailable visualization;
- v2 artifact round-trip and fingerprint tamper detection work;
- live and persisted/restarted API payloads are equal;
- the UI renders available, empty-edge, truncated, and unavailable states;
- Chromium at 390 pixels has no document overflow;
- chain 1072 and other unavailable exact-Audit paths do not trigger dense
  fallback or visualization recomputation.
