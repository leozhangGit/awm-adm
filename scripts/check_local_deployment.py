"""Validate the supported login-free Compose publication without reading secret contents."""

import argparse
import json
import subprocess
from pathlib import Path


def validate(document):
    services = document.get("services", {})
    app = services.get("app", {})
    ports = app.get("ports", [])
    if len(ports) != 1:
        raise ValueError("Publish exactly one application port on 127.0.0.1")
    port = ports[0]
    if (
        port.get("host_ip") != "127.0.0.1"
        or str(port.get("published")) != str(port.get("target"))
        or port.get("protocol", "tcp") != "tcp"
        or not 1024 <= int(port.get("target", 0)) <= 65535
    ):
        raise ValueError("Console/API publication requires matching loopback host/container ports")
    for name, service in services.items():
        if name != "app" and service.get("ports"):
            raise ValueError("Private service ports must not be published")
        if service.get("network_mode") == "host":
            raise ValueError("Host networking is not supported for the login-free stack")
        if any("docker.sock" in str(v) for v in service.get("volumes", [])):
            raise ValueError("The application stack must not mount the Docker socket")
    return int(port["target"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, action="append")
    args = parser.parse_args()
    command = ["docker", "compose"]
    for path in args.file or []:
        command += ["--file", str(path)]
    result = subprocess.run(command + ["config", "--format", "json"], check=True, capture_output=True)
    port = validate(json.loads(result.stdout))
    print(f"Local deployment checked: console/API on 127.0.0.1:{port}; private ports unpublished.")


if __name__ == "__main__":
    main()
