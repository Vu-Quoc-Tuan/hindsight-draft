from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_provider_configuration_is_server_only_and_explicitly_documented() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    expected = {
        "AI_PROVIDER_PROTOCOL": "${AI_PROVIDER_PROTOCOL:-OPENAI_COMPATIBLE}",
        "AI_BASE_URL": "${AI_BASE_URL:-}",
        "AI_API_KEY": "${AI_API_KEY:-}",
        "AI_MODEL": "${AI_MODEL:-}",
    }
    for name, interpolation in expected.items():
        assert services["api"]["environment"][name] == interpolation

    for service_name, service in services.items():
        if service_name == "api":
            continue
        for name in expected:
            assert name not in service.get("environment", {})

    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for name in expected:
        assert f"{name}=" in example
    assert not any(
        line.strip().startswith("VITE_AI_") and "=" in line
        for line in example.splitlines()
    )
