"""Build-time installation of a pinned official Lean archive; no serving downloads."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

lock = json.loads(Path(sys.argv[1]).read_text())
platform = sys.argv[2]
if platform not in lock["platforms"]:
    raise SystemExit("This image currently supports only verified Linux ARM64")
entry = lock["platforms"][platform]
with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    archive = directory / "lean.tar.zst"
    hasher = hashlib.sha256()
    with urllib.request.urlopen(entry["url"], timeout=120) as response, archive.open("wb") as output:
        total = 0
        while chunk := response.read(1_048_576):
            total += len(chunk)
            if total > entry["bytes"]:
                raise ValueError("Lean archive exceeds pinned size")
            hasher.update(chunk)
            output.write(chunk)
    if total != entry["bytes"] or hasher.hexdigest() != entry["sha256"]:
        raise ValueError("Lean archive differs from pinned content")
    subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", temporary], check=True)
    shutil.move(str(directory / entry["root"]), "/opt/lean")
subprocess.run(["/opt/lean/bin/lean", "--version"], check=True)
Path("/opt/lean/awm-adm-toolchain.json").write_text(json.dumps(entry, indent=2) + "\n")
