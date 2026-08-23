import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Keep every test on one timezone regardless of the machine running them.
os.environ.setdefault("TIMEZONE", "America/New_York")
