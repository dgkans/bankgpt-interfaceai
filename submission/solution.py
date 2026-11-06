"""
Submission entry point: build() returns the KnowledgeSystem defined in kb/system.py.

Kept thin on purpose; see NOTES.md for how the system decides what is current.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kb.system import KnowledgeSystem  # noqa: E402

logging.getLogger("kb").setLevel(logging.WARNING)


def build() -> KnowledgeSystem:
    """Entry point called by the harness."""
    return KnowledgeSystem()
