"""Versioned, deterministic project knowledge retrieval for the Assistant."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


_TOKEN = re.compile(r"[a-z0-9_]+")
_REQUIRED = {
    "id",
    "category",
    "title",
    "aliases",
    "definition",
    "interpretation",
    "formula",
    "availability",
    "must_not_claim",
    "sources",
}


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _tokens(value: str) -> set[str]:
    return set(_TOKEN.findall(_normalized(value)))


def _rank(entry: Mapping[str, Any], query: str, tokens: set[str]) -> int:
    normalized_query = _normalized(query).strip()
    entry_id = _normalized(str(entry["id"]))
    title = _normalized(str(entry["title"]))
    aliases = [_normalized(str(alias)) for alias in entry["aliases"]]
    searchable = " ".join(
        [entry_id, title, *aliases, _normalized(str(entry["definition"])), _normalized(str(entry["interpretation"]))]
    )
    score = 0
    if normalized_query and normalized_query in {entry_id, title, *aliases}:
        score += 100
    if normalized_query and normalized_query in searchable:
        score += 30
    searchable_tokens = _tokens(searchable)
    score += 8 * len(tokens & searchable_tokens)
    score += sum(5 for alias in aliases if alias and alias in normalized_query)
    return score


@dataclass(frozen=True)
class KnowledgeCatalog:
    version: str
    entries: tuple[dict[str, Any], ...]

    @classmethod
    def load_default(cls) -> "KnowledgeCatalog":
        raw = json.loads(
            Path(__file__).with_name("assistant_knowledge.json").read_text(encoding="utf-8")
        )
        if not isinstance(raw, dict) or not isinstance(raw.get("version"), str):
            raise ValueError("knowledge catalog requires a string version")
        raw_entries = raw.get("entries")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise ValueError("knowledge catalog requires non-empty entries")
        seen: set[str] = set()
        entries: list[dict[str, Any]] = []
        for index, value in enumerate(raw_entries):
            if not isinstance(value, dict) or not _REQUIRED <= value.keys():
                raise ValueError(f"knowledge entry {index} is missing required fields")
            entry_id = value["id"]
            if not isinstance(entry_id, str) or not entry_id or entry_id in seen:
                raise ValueError(f"knowledge entry id is empty or duplicated: {entry_id!r}")
            if not isinstance(value["aliases"], list) or not all(
                isinstance(alias, str) and alias for alias in value["aliases"]
            ):
                raise ValueError(f"knowledge entry {entry_id} requires string aliases")
            if not isinstance(value["sources"], list) or not value["sources"]:
                raise ValueError(f"knowledge entry {entry_id} requires sources")
            if not isinstance(value["definition"], str) or not value["definition"].strip():
                raise ValueError(f"knowledge entry {entry_id} requires a definition")
            seen.add(entry_id)
            entries.append(dict(value))
        return cls(version=raw["version"], entries=tuple(entries))

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        tokens = _tokens(query)
        eligible = [
            entry
            for entry in self.entries
            if category is None or entry["category"] == category
        ]
        ranked = sorted(
            eligible,
            key=lambda entry: (-_rank(entry, query, tokens), str(entry["id"])),
        )
        return [
            dict(entry)
            for entry in ranked
            if _rank(entry, query, tokens) > 0
        ][: max(1, min(int(limit), 5))]


def knowledge_result_message(entries: Sequence[Mapping[str, Any]]) -> str:
    if not entries:
        return "Không tìm thấy thuật ngữ phù hợp trong kho kiến thức dự án."
    blocks = []
    for entry in entries:
        formula = entry.get("formula") or {}
        formula_text = formula.get("plain") if isinstance(formula, Mapping) else None
        block = (
            f"**{entry['title']}**\n\n{entry['definition']}\n\n"
            f"Ý nghĩa: {entry['interpretation']}\n\n"
            f"Ranh giới: {entry['must_not_claim']}"
        )
        if formula_text:
            block += f"\n\nCông thức: `{formula_text}`"
        blocks.append(block)
    return "\n\n---\n\n".join(blocks)
