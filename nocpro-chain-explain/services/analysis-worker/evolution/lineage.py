"""Step 3-4: bipartite lineage and evolving-chain components (§7, ADR-0020).

Edge rule:

    standard:  n_ij >= m_min (3) AND (containParent >= beta_p OR containChild >= beta_c)
    exception: min(|C_i|, |C_j|) < m_min  =>  exact containment / Jaccard rule

The small-chain exception exists because a 2-member chain can never reach
``n_ij >= 3``, so the standard rule would make every small chain look like NEW +
DISSOLVE instead of CONTINUE.

Components with >= 2 parents **and** >= 2 children are RECOMBINATION. The spec is
explicit that these must not be forced into clean split/merge.

Three separate identifiers are kept (ADR-0020):

    lineage_component_id   component of the episode DAG (Similar Chains dedup)
    branch_id              branch after a split
    snapshot_chain_id      NocPro's raw per-snapshot ID
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Minimum shared alarms for a standard lineage edge.
DEFAULT_M_MIN = 3

#: Containment thresholds: share of parent / child covered by the intersection.
DEFAULT_BETA_PARENT = 0.5
DEFAULT_BETA_CHILD = 0.5

#: Jaccard floor used by the small-chain exception.
DEFAULT_SMALL_CHAIN_JACCARD = 0.5


@dataclass(frozen=True)
class LineageEdge:
    """One parent -> child correspondence on ``Active_both``."""

    parent_chain_id: str
    child_chain_id: str
    shared: int
    parent_size: int
    child_size: int
    #: True when matched under the small-chain exception.
    small_chain_rule: bool = False

    @property
    def contain_parent(self) -> float:
        return self.shared / self.parent_size if self.parent_size else 0.0

    @property
    def contain_child(self) -> float:
        return self.shared / self.child_size if self.child_size else 0.0

    @property
    def jaccard(self) -> float:
        union = self.parent_size + self.child_size - self.shared
        return self.shared / union if union else 0.0


@dataclass
class LineageConfig:
    """Versioned lineage thresholds (ADR-0025)."""

    config_version: str
    m_min: int = DEFAULT_M_MIN
    beta_parent: float = DEFAULT_BETA_PARENT
    beta_child: float = DEFAULT_BETA_CHILD
    small_chain_jaccard: float = DEFAULT_SMALL_CHAIN_JACCARD


def build_lineage_edges(
    previous: dict[str, frozenset[str]],
    current: dict[str, frozenset[str]],
    config: LineageConfig,
) -> list[LineageEdge]:
    """Build bipartite lineage edges between two restricted partitions."""
    edges: list[LineageEdge] = []

    for parent_id in sorted(previous):
        parent_members = previous[parent_id]
        for child_id in sorted(current):
            child_members = current[child_id]
            shared = len(parent_members & child_members)
            if shared == 0:
                continue

            edge = LineageEdge(
                parent_chain_id=parent_id,
                child_chain_id=child_id,
                shared=shared,
                parent_size=len(parent_members),
                child_size=len(child_members),
            )

            small = min(len(parent_members), len(child_members)) < config.m_min
            if small:
                # Exception: exact containment or a Jaccard floor.
                exact_containment = (
                    parent_members <= child_members or child_members <= parent_members
                )
                if exact_containment or edge.jaccard >= config.small_chain_jaccard:
                    edges.append(
                        LineageEdge(
                            parent_chain_id=parent_id,
                            child_chain_id=child_id,
                            shared=shared,
                            parent_size=len(parent_members),
                            child_size=len(child_members),
                            small_chain_rule=True,
                        )
                    )
                continue

            if shared >= config.m_min and (
                edge.contain_parent >= config.beta_parent
                or edge.contain_child >= config.beta_child
            ):
                edges.append(edge)

    return edges


@dataclass
class LineageComponent:
    """One connected component of the episode DAG."""

    lineage_component_id: str
    parents: tuple[str, ...]
    children: tuple[str, ...]
    edges: tuple[LineageEdge, ...]

    @property
    def is_recombination(self) -> bool:
        """>= 2 parents and >= 2 children: not forced into split or merge."""
        return len(self.parents) >= 2 and len(self.children) >= 2

    @property
    def is_split(self) -> bool:
        return len(self.parents) == 1 and len(self.children) >= 2

    @property
    def is_merge(self) -> bool:
        return len(self.parents) >= 2 and len(self.children) == 1

    @property
    def is_one_to_one(self) -> bool:
        return len(self.parents) == 1 and len(self.children) == 1


def build_lineage_components(edges: list[LineageEdge]) -> list[LineageComponent]:
    """Group lineage edges into connected components via union-find."""
    parent_of: dict[str, str] = {}

    def find(node: str) -> str:
        parent_of.setdefault(node, node)
        while parent_of[node] != node:
            parent_of[node] = parent_of[parent_of[node]]
            node = parent_of[node]
        return node

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent_of[right_root] = left_root

    # Namespaced so a parent and child sharing a raw ID stay distinct.
    for edge in edges:
        union(f"P:{edge.parent_chain_id}", f"C:{edge.child_chain_id}")

    grouped: dict[str, list[LineageEdge]] = {}
    for edge in edges:
        grouped.setdefault(find(f"P:{edge.parent_chain_id}"), []).append(edge)

    components: list[LineageComponent] = []
    for index, root in enumerate(sorted(grouped)):
        member_edges = grouped[root]
        parents = tuple(sorted({e.parent_chain_id for e in member_edges}))
        children = tuple(sorted({e.child_chain_id for e in member_edges}))
        components.append(
            LineageComponent(
                lineage_component_id=f"lc_{index:04d}",
                parents=parents,
                children=children,
                edges=tuple(member_edges),
            )
        )
    return components


@dataclass
class LineageAssignment:
    """Identifier assignment for one current-snapshot chain."""

    snapshot_chain_id: str
    lineage_component_id: str | None
    branch_id: str | None

    @property
    def has_lineage(self) -> bool:
        return self.lineage_component_id is not None


def assign_identifiers(
    components: list[LineageComponent], current_chain_ids: set[str]
) -> dict[str, LineageAssignment]:
    """Assign lineage component and branch IDs to current chains.

    A chain with no lineage edge keeps ``None``, which the classifier reads as
    NEW rather than inventing a component for it.
    """
    assignments: dict[str, LineageAssignment] = {}

    for component in components:
        for position, child_id in enumerate(component.children):
            # Branch IDs only mean something when a component has several children.
            branch_id = (
                f"{component.lineage_component_id}:b{position}"
                if len(component.children) > 1
                else f"{component.lineage_component_id}:b0"
            )
            assignments[child_id] = LineageAssignment(
                snapshot_chain_id=child_id,
                lineage_component_id=component.lineage_component_id,
                branch_id=branch_id,
            )

    for chain_id in sorted(current_chain_ids):
        assignments.setdefault(
            chain_id,
            LineageAssignment(
                snapshot_chain_id=chain_id,
                lineage_component_id=None,
                branch_id=None,
            ),
        )
    return assignments
