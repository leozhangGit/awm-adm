"""Report locked versions and publisher-supplied license metadata; not a license audit."""

import hashlib
import importlib.metadata
import json
import tomllib
from pathlib import Path


def inventory(root: Path):
    python_packages = []
    for package in tomllib.loads((root / "uv.lock").read_text())["package"]:
        if package["name"] == "awm-adm":
            continue
        entry = {"name": package["name"], "version": package["version"], "source": package["source"]}
        try:
            dist = importlib.metadata.distribution(package["name"])
            entry.update(
                license=dist.metadata.get("License-Expression")
                or dist.metadata.get("License")
                or "not declared",
                license_files=dist.metadata.get_all("License-File", []),
            )
            if dist.version != package["version"]:
                raise ValueError("Installed Python dependency differs from lock")
        except importlib.metadata.PackageNotFoundError:
            entry.update(license="metadata unavailable", license_files=[])
        python_packages.append(entry)
    node_packages = []
    for path, package in json.loads((root / "console/package-lock.json").read_text())["packages"].items():
        if not path:
            continue
        local = root / "console" / path / "package.json"
        installed = json.loads(local.read_text()) if local.exists() else None
        if installed is not None and installed.get("version") != package["version"]:
            raise ValueError("Installed Node dependency differs from lock")
        node_packages.append(
            {
                "path": path,
                "version": package["version"],
                "resolved": package.get("resolved"),
                "integrity": package.get("integrity"),
                "license": package.get("license") or (installed or {}).get("license") or "not declared",
            }
        )
    return {
        "scope": "Locked dependency provenance and declared licenses, not a vulnerability or redistribution clearance",
        "lock_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("uv.lock", "console/package-lock.json")
        },
        "python": python_packages,
        "node": node_packages,
        "container_images": json.loads((root / "deploy/image-lock.json").read_text())["images"],
        "container_status": "Pinned Linux ARM64 runtime; supported runtime checks record actual image identities and execution outcomes",
        "project_license": "MIT; third-party dependencies retain their own licenses",
    }


if __name__ == "__main__":
    print(json.dumps(inventory(Path(__file__).resolve().parents[1]), indent=2))
