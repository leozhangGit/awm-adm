"""Local service CLI and offline owner operations."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .api import create_app, system_info
from .config import load_config
from .schemas import export_schemas


def main(argv=None):
    import sys

    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] == "operations":
        from .operations.backup import main as operations_main

        return operations_main(arguments[1:])
    if arguments and arguments[0] == "operator":
        from .runtime.operator import main as operator_main

        return operator_main(arguments[1:])
    parser = argparse.ArgumentParser(prog="awm-adm")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("operations", help="Quiesced service backup, verification and restore")
    commands.add_parser("info", help="Report actual implemented capabilities")
    commands.add_parser("operator", help="Use authenticated private instance and local-compute commands")
    config = commands.add_parser("check-config", help="Validate TOML configuration without loading secrets")
    config.add_argument("path", type=Path)
    schema = commands.add_parser("schemas", help="Export boundary JSON Schemas")
    schema.add_argument("--output", type=Path, required=True)
    schema.add_argument(
        "--check", action="store_true", help="Check generated schemas without modifying files"
    )
    serve = commands.add_parser("dev-serve", help="Run loopback development status endpoints only")
    serve.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "info":
            print(json.dumps(system_info(), indent=2))
        elif args.command == "check-config":
            value = load_config(args.path)
            print(
                json.dumps(
                    {
                        "valid": True,
                        "config_profile": value.config_profile,
                        "remote_calls_enabled": value.learning.remote_calls_enabled,
                    }
                )
            )
        elif args.command == "schemas":
            export_schemas(args.output, check=args.check)
        else:
            import uvicorn

            value = load_config(args.config)
            uvicorn.run(create_app(value), host=value.server.bind_host, port=value.server.port)
    except ValidationError as exc:
        # Reject unknown fields without echoing supplied values (which might include a secret).
        print(
            json.dumps(
                {
                    "valid": False,
                    "errors": [
                        {"loc": list(e["loc"]), "type": e["type"]}
                        for e in exc.errors(include_input=False, include_context=False)
                    ],
                }
            )
        )
        return 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": type(exc).__name__}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
