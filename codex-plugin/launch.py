"""Start the installed plugin environment without installing at tool-call time."""

import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
python = root / ".venv" / "bin" / "python"
if not python.is_file():
    print("AWM-ADM plugin runtime is missing. Complete the documented plugin setup first.", file=sys.stderr)
    raise SystemExit(1)
os.execv(str(python), [str(python), "-I", "-m", "awm_adm_plugin.server"])
