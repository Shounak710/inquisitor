"""Inquisitor controller v1.

v1 decides which questions to ask before the coding model runs.
"""

from controller.v1.loop import run_task
from controller.v1.types import Mode

__version__ = "v1"

__all__ = ["Mode", "__version__", "run_task"]
