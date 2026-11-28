"""Write a new configuration; never edit the input or contact a service."""

import argparse
import json
import sys
import tomllib
from pathlib import Path

from pydantic import ValidationError

from awm_adm.config_conversion import convert, toml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--input-reservation", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--timeout-seconds", type=int)
    args = parser.parse_args()
    values = (args.input_reservation, args.output_tokens, args.timeout_seconds)
    if any(v is not None for v in values) and not all(v is not None for v in values):
        parser.error("Supply all three shared limits together")
    call = (
        None
        if values == (None, None, None)
        else {
            "max_input_tokens": values[0],
            "max_output_tokens": values[1],
            "max_duration_ms": values[2] * 1000,
        }
    )
    try:
        result, report = convert(tomllib.loads(args.source.read_text()), call=call)
        with args.destination.open("x") as stream:
            stream.write(toml(result.model_dump()))
    except ValidationError:
        print(
            "Configuration contains invalid fields or limits; no converted file was written", file=sys.stderr
        )
        return 2
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
