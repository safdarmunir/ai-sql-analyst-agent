from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"

sys.path.insert(0, str(FRONTEND_DIR))

source = FRONTEND_DIR / "app.py"
exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"))
