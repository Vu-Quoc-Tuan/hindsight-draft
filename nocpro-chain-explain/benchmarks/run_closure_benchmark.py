"""Write the consolidated closure benchmark manifest without running Docker.

The existing ``run_benchmark.py`` remains the real-export Tier-1 measurement
runner.  This command records the complete, versioned measurement matrix so
that unavailable and runtime-only measurements are never silently omitted.
Use it before an environment-specific benchmark run; it does not start Docker
or replay data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Support the documented direct invocation from the chain-explain root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.closure import closure_manifest, empty_closure_results


def run(output: Path | None = None) -> Path:
    root = Path(__file__).resolve().parent
    target = output or root / "results" / "closure-latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = closure_manifest()
    payload["results"] = empty_closure_results()
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Closure benchmark manifest written to {target}")
    return target


if __name__ == "__main__":
    run()
