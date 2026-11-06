"""
The harness contract types (Answer, Source, Conflict), imported from the grader's copy.

We walk up from this file to find harness/contract.py so the grader's own dataclasses are
used. If it is not found (e.g. the package is imported standalone in tests), identical
local dataclasses are used; the harness accepts any object with the same fields.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


def _find_harness() -> Optional[Path]:
    """Folder holding the grader's contract.py, searched upwards from this file."""
    for d in Path(__file__).resolve().parents:
        if (d / "harness" / "contract.py").exists():
            return d / "harness"
    return None


_HARNESS = _find_harness()
if _HARNESS is not None and str(_HARNESS) not in sys.path:
    sys.path.insert(0, str(_HARNESS))

try:
    from contract import Answer, Conflict, Snapshot, Source  # type: ignore  # noqa: F401
except ImportError:  # standalone use: same fields as harness/contract.py
    @dataclass
    class Source:  # type: ignore[no-redef]
        url: str
        snapshot_id: Optional[str] = None
        quote: Optional[str] = None

    @dataclass
    class Answer:  # type: ignore[no-redef]
        text: str
        sources: List[Source] = field(default_factory=list)
        confident: bool = True
        conflict_note: Optional[str] = None

    @dataclass
    class Conflict:  # type: ignore[no-redef]
        topic: str
        values: List[str]
        sources: List[Source]
        resolution: Optional[str] = None
        reason: Optional[str] = None

    Snapshot = None  # type: ignore[assignment]
