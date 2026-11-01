"""Inquisitor controllers.

v1 decides which questions to ask before the coding model runs.
v2 gives the model lookup_decisions and ask_human.
"""

from controller.v1 import Mode, __version__, run_task

__all__ = ["Mode", "__version__", "run_task"]
