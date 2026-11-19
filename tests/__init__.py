"""Load the pure-Python modules without running the package __init__ (needs Home Assistant)."""

import sys
import types
from pathlib import Path

_pkg = Path(__file__).resolve().parent.parent / "custom_components" / "sunsprout_monitor"
for name, path in (("custom_components", _pkg.parent), ("custom_components.sunsprout_monitor", _pkg)):
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = [str(path)]
        sys.modules[name] = m
