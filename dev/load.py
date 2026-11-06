"""Dev helper: load snapshots with the harness loader (not used by the solution)."""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness")); sys.path.insert(0, str(ROOT / "submission"))
from run_eval import load_snapshots  # noqa
def snaps(selftest=False):
    return load_snapshots(ROOT / ("harness/selftest/snapshots" if selftest else "snapshots"))
