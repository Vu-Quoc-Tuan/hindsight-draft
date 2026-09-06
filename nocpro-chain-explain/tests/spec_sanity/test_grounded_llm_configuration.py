from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_provider_protocol_is_server_only_and_explicitly_documented() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    assert services["api"]["environment"]["AI_PROVIDER_PROTOCOL"] == (
        "${AI_PROVIDER_PROTOCOL:-OPENAI_COMPATIBLE}"
    )
    for service_name, service in services.items():
        if service_name == "api":
            continue
        assert "AI_PROVIDER_PROTOCOL" not in service.get("environment", {})

    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "AI_PROVIDER_PROTOCOL=OPENAI_COMPATIBLE" in example
    assert not any(
        line.strip().startswith("VITE_AI_") and "=" in line
        for line in example.splitlines()
    )
