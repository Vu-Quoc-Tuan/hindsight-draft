from pathlib import Path

from nocpro_api.assistant_knowledge import KnowledgeCatalog, knowledge_fallback_message


def test_default_catalog_covers_frozen_methodology_domains():
    catalog = KnowledgeCatalog.load_default()
    ids = {entry["id"] for entry in catalog.entries}
    assert {
        "metric.conductance",
        "metric.membership_support",
        "metric.fit_group",
        "metric.margin_common",
        "audit.deletion_auc",
        "evolution.lineage",
        "similarity.cosine",
        "status.unavailable",
        "topology.propagation_hypothesis",
        "review.pareto_frontier",
    } <= ids


def test_alias_and_formula_search_returns_complete_entry():
    entry = KnowledgeCatalog.load_default().search("phi độ dẫn")[0]
    assert entry["id"] == "metric.conductance"
    assert entry["formula"]["latex"]
    assert entry["must_not_claim"]
    assert entry["sources"]


def test_search_is_accent_insensitive_bounded_and_deterministic():
    catalog = KnowledgeCatalog.load_default()
    assert catalog.search("do ho tro thanh vien", limit=1)[0]["id"] == "metric.membership_support"
    assert len(catalog.search("metric", limit=99)) <= 5
    assert catalog.search("xyzzy qqqq") == []


def test_fallback_message_keeps_formula_and_boundary():
    entries = KnowledgeCatalog.load_default().search("conductance", limit=1)
    message = knowledge_fallback_message(entries)
    assert "Phi(S)" in message
    assert "Ranh giới" in message


def test_catalog_source_paths_exist_in_project() -> None:
    project_root = Path(__file__).resolve().parents[1]
    for entry in KnowledgeCatalog.load_default().entries:
        for source in entry["sources"]:
            assert (project_root / source).exists(), f"missing source for {entry['id']}: {source}"
