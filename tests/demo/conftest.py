import sys
from pathlib import Path

# The demo lives under scripts/, not in an installed package; tests import it the way the entrypoint does.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "demo"))
