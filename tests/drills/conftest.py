import sys
from pathlib import Path

# The drills live under scripts/ and reuse the demo's modules; tests import them the way the entrypoint does.
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
for folder in ("demo", "drills"):
    sys.path.insert(0, str(SCRIPTS / folder))
