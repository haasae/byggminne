"""Put the repo root on sys.path so `import src.<pkg>` works under pytest even
with an interpreter that has not `pip install -e .`'d the package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
