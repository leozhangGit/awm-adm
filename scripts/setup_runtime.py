"""Create distinct local service tokens without displaying or replacing them."""

import base64
import os
import secrets
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1] / ".local/secrets"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise ValueError("Secret directory must not be a symlink")
    root.chmod(0o700)
    for role in ("owner", "worker", "gateway"):
        path = root / (role + "-token")
        if path.exists():
            if path.is_symlink():
                raise ValueError("Secret file must not be a symlink")
            continue
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_urlsafe(48) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Docker file mounts must be readable by the non-root container UID.
        # The containing host directory remains owner-only.
        path.chmod(0o444)
    master = root / "gateway-master-key"
    if master.is_symlink():
        raise ValueError("Gateway master key cannot be a symlink")
    if not master.exists():
        fd = os.open(master, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
        with os.fdopen(fd, "wb") as stream:
            stream.write(base64.urlsafe_b64encode(secrets.token_bytes(32)) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        master.chmod(0o444)
    static = root.parent / "provider-secrets"
    if static.is_symlink():
        raise ValueError("Provider secret directory cannot be a symlink")
    static.mkdir(mode=0o755, exist_ok=True)
    print("Local service tokens are ready; existing tokens were preserved. No provider credentials are used.")


if __name__ == "__main__":
    main()
