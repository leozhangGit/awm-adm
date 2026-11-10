"""Run an isolated loopback console for browser verification, without providers."""

import argparse
import os
import secrets
from pathlib import Path

import uvicorn

from awm_adm.api import create_app
from awm_adm.config import AppConfig
from awm_adm.runtime.service import Runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8082)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = args.directory / "owner-token"
    if not token.exists():
        token.write_text(secrets.token_urlsafe(48))
        token.chmod(0o600)
    config = AppConfig.model_validate(
        {
            "server": {"port": args.port, "data_dir": str(args.directory.resolve() / "data")},
            "proof": {"lean_executable": os.environ.get("AWM_ADM_LEAN", "/nonexistent/lean")},
        }
    )
    runtime = Runtime(config)
    try:
        assets = Path(__file__).resolve().parents[1] / "console/dist"
        uvicorn.run(
            create_app(config, runtime=runtime, assets=assets, owner_token=token.read_text()),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
            proxy_headers=False,
        )
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
