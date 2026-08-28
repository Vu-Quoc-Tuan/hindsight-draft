"""nocpro-mock — upstream replay, normalization and scenario simulator.

Emits versioned Input Contract packages for ``nocpro-chain-explain``. It replays
observed data, never reimplements NocPro chaining or Explain methodology.
"""

from .config import GENERATOR_VERSION, MockConfig, load_config

__version__ = "0.1.0"

__all__ = ["GENERATOR_VERSION", "MockConfig", "__version__", "load_config"]
