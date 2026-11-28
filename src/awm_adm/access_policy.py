"""Explicit native-client access over an operator-owned private container network."""

import ipaddress
import re
from typing import Self

from pydantic import Field, model_validator

from .contracts import ClosedModel

PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class TrustedClients(ClosedModel):
    hosts: list[str] = Field(default_factory=list, max_length=16)
    source_networks: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def explicit_private_access(self) -> Self:
        if bool(self.hosts) != bool(self.source_networks):
            raise ValueError("Trusted clients require both hosts and source_networks, or neither")
        if len(set(self.hosts)) != len(self.hosts) or len(set(self.source_networks)) != len(
            self.source_networks
        ):
            raise ValueError("Trusted client entries must be unique")
        for host in self.hosts:
            name, separator, port = host.rpartition(":")
            if (
                not separator
                or len(name) > 253
                or not all(LABEL.fullmatch(label) for label in name.split("."))
                or not port.isascii()
                or len(port) > 5
                or not port.isdecimal()
                or not 1024 <= int(port) <= 65535
                or str(int(port)) != port
            ):
                raise ValueError(
                    "Trusted hosts must be exact lowercase DNS names or IPv4 addresses with a port"
                )
            if name == "localhost" or name.endswith(".localhost"):
                raise ValueError("Loopback authorities are reserved for local workspace access")
            try:
                address = ipaddress.ip_address(name)
            except ValueError:
                address = None
            if address is not None and not any(
                address.version == network.version and address in network for network in PRIVATE_NETWORKS
            ):
                raise ValueError("Numeric trusted hosts must be private addresses")
        for value in self.source_networks:
            if "/" not in value:
                raise ValueError("Trusted source networks require an explicit CIDR prefix")
            network = ipaddress.ip_network(value, strict=True)
            if str(network) != value or not any(
                network.version == private.version and network.subnet_of(private)
                for private in PRIVATE_NETWORKS
            ):
                raise ValueError("Trusted source networks must be canonical private IPv4 or ULA IPv6 CIDRs")
        return self


class TrustedClientAccess:
    def __init__(self, policy: TrustedClients):
        self.hosts = frozenset(policy.hosts)
        self.networks = tuple(ipaddress.ip_network(value) for value in policy.source_networks)

    def permits(self, host: str, peer: str) -> bool:
        if host not in self.hosts:
            return False
        try:
            address = ipaddress.ip_address(peer)
        except ValueError:
            return False
        return any(address.version == network.version and address in network for network in self.networks)
