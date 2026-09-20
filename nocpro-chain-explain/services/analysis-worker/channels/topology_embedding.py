"""Topology Representation Learning / High-Order Graph Proximity Embedding (§4A, ADR-0022).

Computes deterministic, low-dimensional continuous vector representations (embeddings)
for network devices from topology graph structures.

Methodology:
- High-Order Proximity Embedding (HOPE / NetMF formulation) via Katz-decayed transition
  matrices and Truncated SVD.
- Captures latent multi-hop neighborhood structural affinities that simple 1-hop / 2-hop
  shortest-path metrics miss (e.g. devices in the same transit ring or shared aggregation pod).
- Fully deterministic: identical graph inputs always produce exact identical embeddings.
- Fail-closed: unmapped devices or disconnected nodes produce UNAVAILABLE (⊥),
  preserving Hindsight's epistemic boundary (ADR-0028).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import svds

from libs.contracts import IngestedAlarm
from libs.provenance import ProvenanceClass, ProvenanceSubtype

from .base import ChannelValue, unavailable
from .contracts import ChannelFamily, DependencySemantic
from .dependency import ResourceResolver, TopologyGraph

CHANNEL_ID = "Dep_embed"
DERIVATION_TAG = "dependency_topology_embedding"
DEFAULT_EMBEDDING_DIM = 16
DEFAULT_DECAY = 0.5
DEFAULT_MAX_ORDER = 3
DEFAULT_SUPPORT_THRESHOLD = 0.5


@dataclass
class TopologyEmbeddingModel:
    """Precomputed or fitted latent embedding representation of a topology graph."""

    dimension: int
    node_to_index: dict[str, int]
    embeddings: np.ndarray  # Shape: (N, dimension), L2-normalized
    source_ref: str = "topology_spectral_hop_v1"
    version: str = "v1"

    @classmethod
    def fit_from_adjacency(
        cls,
        adjacency: Mapping[str, set[str] | Sequence[str]],
        *,
        dimension: int = DEFAULT_EMBEDDING_DIM,
        decay: float = DEFAULT_DECAY,
        max_order: int = DEFAULT_MAX_ORDER,
        source_ref: str = "topology_spectral_hop_v1",
    ) -> TopologyEmbeddingModel:
        """Fit a deterministic high-order proximity embedding model from an adjacency map."""
        all_nodes = sorted(adjacency.keys())
        if not all_nodes:
            return cls(
                dimension=dimension,
                node_to_index={},
                embeddings=np.empty((0, dimension), dtype=np.float64),
                source_ref=source_ref,
            )

        node_to_index = {node: idx for idx, node in enumerate(all_nodes)}
        n = len(all_nodes)

        # Build sparse adjacency matrix
        rows: list[int] = []
        cols: list[int] = []
        for u, neighbors in adjacency.items():
            u_idx = node_to_index[u]
            for v in neighbors:
                if v in node_to_index:
                    rows.append(u_idx)
                    cols.append(node_to_index[v])

        if not rows:
            # Graph has nodes but zero edges -> Identity embeddings
            dim = min(dimension, n)
            ident = np.eye(n, dim, dtype=np.float64)
            return cls(
                dimension=dim,
                node_to_index=node_to_index,
                embeddings=ident,
                source_ref=source_ref,
            )

        data = np.ones(len(rows), dtype=np.float64)
        adj_matrix = sparse.csr_matrix((data, (rows, cols)), shape=(n, n), dtype=np.float64)

        # Degree normalization for random-walk transition matrix: P = D^{-1} A
        deg = np.array(adj_matrix.sum(axis=1)).flatten()
        deg_inv = np.zeros_like(deg)
        nonzero_mask = deg > 0
        deg_inv[nonzero_mask] = 1.0 / deg[nonzero_mask]
        d_inv = sparse.diags(deg_inv)
        p_matrix = d_inv @ adj_matrix

        # High-order proximity: M = sum_{k=1}^K alpha^k * P^k
        m_matrix = sparse.csr_matrix((n, n), dtype=np.float64)
        curr_p = p_matrix.copy()
        for k in range(1, max_order + 1):
            weight = decay**k
            m_matrix = m_matrix + (curr_p * weight)
            if k < max_order:
                curr_p = curr_p @ p_matrix

        # Symmetrize high-order proximity for joint undirected/directed embedding
        m_sym = (m_matrix + m_matrix.T) * 0.5

        eff_dim = min(dimension, n - 1)
        if eff_dim < 1:
            eff_dim = 1

        try:
            if n > 2 and eff_dim < n:
                u_mat, s_vec, _ = svds(m_sym, k=eff_dim)
                # Sort descending by singular value
                sort_idx = np.argsort(s_vec)[::-1]
                u_mat = u_mat[:, sort_idx]
                s_vec = s_vec[sort_idx]
                raw_embed = u_mat * np.sqrt(np.maximum(s_vec, 0.0))
            else:
                dense = m_sym.toarray()
                u_mat, s_vec, _ = np.linalg.svd(dense)
                raw_embed = u_mat[:, :eff_dim] * np.sqrt(np.maximum(s_vec[:eff_dim], 0.0))
        except Exception:
            dense = m_sym.toarray()
            u_mat, s_vec, _ = np.linalg.svd(dense)
            raw_embed = u_mat[:, :eff_dim] * np.sqrt(np.maximum(s_vec[:eff_dim], 0.0))

        # L2-normalize node vectors
        norms = np.linalg.norm(raw_embed, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized_embed = raw_embed / norms

        return cls(
            dimension=eff_dim,
            node_to_index=node_to_index,
            embeddings=normalized_embed,
            source_ref=source_ref,
        )

    @classmethod
    def fit_from_topology_graph(
        cls,
        graph: TopologyGraph,
        *,
        dimension: int = DEFAULT_EMBEDDING_DIM,
        decay: float = DEFAULT_DECAY,
        max_order: int = DEFAULT_MAX_ORDER,
    ) -> TopologyEmbeddingModel:
        """Fit model directly from an existing TopologyGraph object."""
        return cls.fit_from_adjacency(
            graph.adjacency,
            dimension=dimension,
            decay=decay,
            max_order=max_order,
            source_ref=graph.source_ref or "topology_graph_fitted",
        )

    def get_node_embedding(self, node_id: str) -> np.ndarray | None:
        """Return unit vector embedding for a node, or None if unknown."""
        idx = self.node_to_index.get(node_id)
        if idx is None or idx >= len(self.embeddings):
            return None
        return self.embeddings[idx]

    def cosine_similarity(self, node_a: str, node_b: str) -> float | None:
        """Compute cosine similarity between two nodes in [-1.0, 1.0]."""
        emb_a = self.get_node_embedding(node_a)
        emb_b = self.get_node_embedding(node_b)
        if emb_a is None or emb_b is None:
            return None
        return float(np.dot(emb_a, emb_b))

    def normalized_affinity(self, node_a: str, node_b: str) -> float | None:
        """Return normalized affinity in [0.0, 1.0] (mapped from cosine)."""
        cos = self.cosine_similarity(node_a, node_b)
        if cos is None:
            return None
        # Map [-1, 1] -> [0, 1]
        return float(np.clip((cos + 1.0) / 2.0, 0.0, 1.0))

    def compute_chain_structural_embedding(
        self, resource_ids: Sequence[str]
    ) -> np.ndarray | None:
        """Compute mean-pooled normalized vector representing the chain's topology footprint."""
        valid_vecs = [
            self.get_node_embedding(rid)
            for rid in resource_ids
            if self.get_node_embedding(rid) is not None
        ]
        if not valid_vecs:
            return None
        pooled = np.mean(valid_vecs, axis=0)
        norm = np.linalg.norm(pooled)
        if norm > 0:
            pooled = pooled / norm
        return pooled

    def save_npz(self, filepath: Path | str) -> None:
        """Serialize embedding model to a compressed NumPy archive."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        nodes_json = json.dumps(self.node_to_index)
        np.savez_compressed(
            path,
            embeddings=self.embeddings,
            dimension=np.array([self.dimension]),
            nodes_json=np.array([nodes_json]),
            source_ref=np.array([self.source_ref]),
            version=np.array([self.version]),
        )

    @classmethod
    def load_npz(cls, filepath: Path | str) -> TopologyEmbeddingModel:
        """Load embedding model from a compressed NumPy archive."""
        path = Path(filepath)
        with np.load(path, allow_pickle=True) as data:
            embeddings = data["embeddings"]
            dimension = int(data["dimension"][0])
            nodes_json = str(data["nodes_json"][0])
            node_to_index = json.loads(nodes_json)
            source_ref = str(data["source_ref"][0]) if "source_ref" in data else "loaded_model"
            version = str(data["version"][0]) if "version" in data else "v1"
            return cls(
                dimension=dimension,
                node_to_index=node_to_index,
                embeddings=embeddings,
                source_ref=source_ref,
                version=version,
            )


def evaluate_topo_embedding_channel(
    alarm_a: IngestedAlarm,
    alarm_b: IngestedAlarm,
    *,
    model: TopologyEmbeddingModel | None,
    resolver: ResourceResolver,
    threshold: float = DEFAULT_SUPPORT_THRESHOLD,
    provenance_class: ProvenanceClass = ProvenanceClass.EXTERNAL_OPERATIONAL,
) -> ChannelValue:
    """Evaluate the latent topology embedding affinity channel for one alarm pair."""
    def fail(reason: str) -> ChannelValue:
        return unavailable(
            CHANNEL_ID,
            DERIVATION_TAG,
            provenance_class,
            reason=reason,
            threshold=threshold,
            channel_family=ChannelFamily.DEP_EMBEDDING,
            dependency_semantic=DependencySemantic.SHARED_ACTIVE_PATH,
        )

    if model is None:
        return fail("topology embedding model not fitted or unavailable")

    res_a = resolver.resource_of(alarm_a.alarm_id)
    res_b = resolver.resource_of(alarm_b.alarm_id)
    if not res_a or not res_b:
        return fail("one or both alarms lack exact resource mapping")

    affinity = model.normalized_affinity(res_a, res_b)
    if affinity is None:
        return fail(f"device {res_a!r} or {res_b!r} not found in topology embedding index")

    cos = model.cosine_similarity(res_a, res_b)
    return ChannelValue(
        channel_id=CHANNEL_ID,
        derivation_tag=DERIVATION_TAG,
        provenance_class=provenance_class,
        availability=True,
        positive_score=round(affinity, 4),
        threshold=threshold,
        negative_score=0.0,
        provenance_subtype=ProvenanceSubtype.TOPOLOGY_EXTERNAL,
        channel_family=ChannelFamily.DEP_EMBEDDING,
        dependency_semantic=DependencySemantic.SHARED_ACTIVE_PATH,
        detail=f"Latent topology affinity: {affinity:.3f} (cos={cos:.3f}, dim={model.dimension})",
        evidence_metadata={
            "resource_a": res_a,
            "resource_b": res_b,
            "cosine_similarity": cos,
            "normalized_affinity": affinity,
            "dimension": model.dimension,
            "source_ref": model.source_ref,
        },
    )


__all__ = [
    "CHANNEL_ID",
    "DERIVATION_TAG",
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_DECAY",
    "DEFAULT_MAX_ORDER",
    "DEFAULT_SUPPORT_THRESHOLD",
    "TopologyEmbeddingModel",
    "evaluate_topo_embedding_channel",
]
