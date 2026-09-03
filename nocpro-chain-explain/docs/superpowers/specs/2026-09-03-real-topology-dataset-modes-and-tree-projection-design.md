# Real topology dataset modes and tree projection design

## Purpose

Make the mock and Explain UI accurately expose the three real-data modes that
exist in the repository.  The feature provides a compact topology navigation
view; it does not change the semantics of the Explain evidence engine.

This specification deliberately distinguishes a source-record relationship
from a dependency, causality, upstream path, propagation route, or ownership
claim.

## Dataset modes

The mock has one explicit data-profile selector.  It selects both the alarm
export and the topology source, so a user cannot accidentally replay alarms
from one domain against topology from another.

| Profile | Alarm source | Topology source | Topology capability |
|---|---|---|---|
| `ALARM_ONLY` | `datasets/raw/alarm/alarm_data.csv` | none | `UNAVAILABLE` |
| `IP_NETWORK` | `datasets/raw/alarm/alarmIP.csv` | `datasets/raw/topo/topoIP.csv` | `UNDIRECTED_ADJACENCY` |
| `IT_SERVICES` | `datasets/raw/alarm/alarmIT.csv` | `datasets/raw/topo/topoIT/` | `DIRECTED_SOURCE_RELATIONS` |

The old unqualified mock defaults are removed from the user-facing selection
path.  A caller selecting a profile cannot silently override only one half of
the alarm/topology pair.  Explicit low-level paths remain restricted to test
or developer use, and their source metadata is preserved.

## Source semantics

### Alarm-only

`alarm_data.csv` is replayed without a topology source.  Topology-derived
views and capabilities report `UNAVAILABLE`; an empty graph is not presented
as a topology result.

### IP network

`topoIP.csv` is an undirected adjacency source.  Each normalized edge means
only `ADJACENT_TO`; endpoint order in the CSV is not a direction.

It must not enable `Dep_upstream`, shared ancestor/path, dominator,
propagation, failure-domain, or any dependency capability.  A tree UI is an
**Adjacency Tree Projection**, not a network hierarchy.

### IT services

`topoIT/` is normalized into a directed relation graph.  The supported node
types are `SERVICE`, `MODULE`, `INSTANCE`, `DATABASE`, and `STORAGE`.
Edges retain their source-table relationship type:

```text
SERVICE_HAS_MODULE       SERVICE  -> MODULE
MODULE_HAS_INSTANCE      MODULE   -> INSTANCE
MODULE_LINKS_DATABASE    MODULE   -> DATABASE
DATABASE_LINKS_SERVICE   DATABASE -> SERVICE
DATABASE_LINKS_INSTANCE  DATABASE -> INSTANCE
INSTANCE_LINKS_STORAGE   INSTANCE -> STORAGE
```

Each edge records:

```text
direction_kind = SOURCE_RELATION
dependency_semantics = UNVERIFIED
source_table
source_id / source_version
provenance
```

The source can contain cycles.  It is therefore a **directed relation graph**,
not a claimed DAG, dependency topology, or propagation graph.  It must not
enable `Dep_upstream`, `SHARED_ANCESTOR`, `DOMINATOR`,
`PROPAGATION_HYPOTHESIS`, or any other P2 dependency semantic without a
separate authoritative business contract.

## Normalized topology relation model

React never reads raw CSV files.  The mock/API owns normalization to:

```text
TopologyRelationNode
  resource_id
  resource_type
  display_name
  source metadata

TopologyRelationEdge
  source_id
  target_id
  relation_type
  direction_kind
  dependency_semantics
  source_table
  source_version
  provenance
```

Resource IDs are namespace-qualified and stable, for example
`it:service:<id>` and `it:database:<id>`.  Raw identifiers from distinct
tables must not collide.

Alarm-to-resource mapping remains an independent exact-identity gate.  No
name, prefix, or approximate matching is introduced.  An IT alarm that cannot
be mapped by an explicitly verified source key stays unmapped; this UI feature
does not open topology-derived Explain capabilities.

## Tree projection

The UI renders a bounded navigation projection rather than trying to draw the
whole raw graph.

### IT projection

The default root is a selected `SERVICE`.  Its primary navigational shape is:

```text
Service
  Modules
    Module
      Instances
      Databases
  Direct database relations
```

The labels describe source-record links, not ownership or operational
dependency.  A persistent notice states:

> This relation-tree projection is for navigation.  It does not imply
> dependency, causality, ownership, or propagation direction.

### IP projection

The default root is a selected device and follows adjacency edges.  The UI
labels it **Adjacency Tree Projection** and makes its undirected source
semantics visible.

### Multi-parent and cycle handling

The raw relation graph is never duplicated recursively.

* A node receives one technical, deterministic primary occurrence using
  relation-display priority, source-type priority, then stable parent ID.
* The primary path has no domain semantics.
* Other incoming links are shown as a reference badge, such as “also linked
  from 3 modules”, expandable in the inspector.
* A per-path `visited_path` guard stops recursion.  A target that is already
  on that path is rendered as a non-expandable cycle reference, for example
  “linked to Service S1”.

The server applies bounded depth and child limits and exposes total/hidden
counts.  The client initially expands only shallow levels, supports search and
type filters, and loads deeper branches only on request.  It never renders all
rows of the IT source at once.

## UI boundaries

Topology navigation is a separate view from the existing Chain Tree, which
organizes alarms within a chain.  The new view may cross-link to a selected
alarm or resource only when an exact mapping exists.

The view uses a compact, operator-oriented layout:

* profile/source badge and explicit semantic notice at the top;
* searchable, filtered tree at left/center;
* node inspector at right or below on narrow screens;
* relationship type, source table, and direction-kind in the inspector;
* clear `UNAVAILABLE` state for alarm-only or absent source data;
* no causal, root-cause, dependency, or propagation wording.

## Error handling and fail-closed behavior

* Missing profile files yield an explicit unavailable/error response; no
  automatic switch to another profile occurs.
* Unrecognized or incomplete CSV schema fails profile preparation with the
  source table and missing-column diagnostic.
* An IT cycle is valid graph data and is projected safely, not rejected or
  recursively expanded.
* Unverified direction semantics remain `SOURCE_RELATION`; the presentation
  layer cannot promote it to `LOGICAL_DEPENDENCY`.
* Missing/ambiguous alarm-resource mappings remain `UNMAPPED`.

## Tests and acceptance

Tests must cover:

1. deterministic profile selection and correct alarm/topology pairing;
2. `ALARM_ONLY` topology unavailable state;
3. IP edges retained as undirected adjacency;
4. IT normalized node namespaces and typed directed source relations;
5. schema diagnostics and no heuristic mapping;
6. deterministic primary occurrence for multi-parent nodes;
7. cycle guard with a `SERVICE -> MODULE -> DATABASE -> SERVICE` fixture;
8. bounded projection and child/hidden counts;
9. UI labels/notices for IP versus IT semantics;
10. browser test with no console errors and no misleading dependency wording;
11. regression that this work does not make any P2 dependency capability
    available for real IP or IT data.

## Non-goals

* no Louvain internal explanation: observed `chaining_id` remains a black-box
  NocPro result and Explain remains post-hoc;
* no topology-based production dependency, active-path, dominator, propagation,
  scope-overlap, or failure-domain analysis;
* no fuzzy alarm-to-resource mapping;
* no conversion of the complete relation graph into an ownership tree;
* no modification to Counterfactual Review, H, T_delay, thresholds, or
  production calibration.
