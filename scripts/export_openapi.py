"""Generate the public API contract offline, using a disposable empty store."""

import argparse
import json
import tempfile
from pathlib import Path

from awm_adm.api import create_app
from awm_adm.config import AppConfig
from awm_adm.runtime.service import Runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("contracts/openapi.json"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="awm-adm-openapi-") as temporary:
        config = AppConfig.model_validate({"server": {"data_dir": temporary}})
        runtime = Runtime(config, start_scheduler=False)
        try:
            app = create_app(config, runtime=runtime, owner_token="offline-contract-" + "x" * 48)
            args.output.write_text(json.dumps(app.openapi(), indent=2) + "\n")
        finally:
            runtime.close()


if __name__ == "__main__":
    main()
