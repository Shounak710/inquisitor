"""Inquisitor controller v2.

The model is told to call lookup_decisions before a significant design
decision, and ask_human when that lookup finds nothing.
"""

from controller.v2.loop import run_v2

__version__ = "v2"

__all__ = ["__version__", "run_v2"]
