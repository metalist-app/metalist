"""This computer's own names and addresses, as they are now.

A vault shared on the network accepts requests addressed to any of them without a list kept by
hand (docs/security/README.md, "Sharing on the Network"): the address the router gives the
computer can change while MetaList runs, so it is looked up when a request needs it. A hostile
page that rebinds its own domain to this computer still sends its own domain as the Host, which
is none of these, so the check against DNS rebinding holds.
"""
from __future__ import annotations

import ipaddress
import socket

import psutil

# Multicast DNS names (RFC 6762): Macs, iPhones, current Windows and Linux with Avahi answer to
# <name>.local on the local network.
_MULTICAST_DNS_SUFFIX = ".local"
_ADDRESS_FAMILIES = frozenset({socket.AF_INET, socket.AF_INET6})
# An IPv6 link-local address may carry its interface after a percent sign (fe80::1%en0).
_IPV6_ZONE_SEPARATOR = "%"


def own_host_names() -> frozenset[str]:
    """The computer's name as the system reports it, and its multicast DNS name."""
    hostname = socket.gethostname().strip().casefold().rstrip(".")
    if hostname == "":
        raise RuntimeError("The computer reported an empty host name")
    first_label = hostname.split(".")[0]
    return frozenset({hostname, f"{first_label}{_MULTICAST_DNS_SUFFIX}"})


def own_ip_addresses() -> frozenset[str]:
    """Every address on this computer's network interfaces now, written as Host headers are
    normalized (app/security/request_hosts.py)."""
    addresses: set[str] = set()
    for interface_addresses in psutil.net_if_addrs().values():
        for interface_address in interface_addresses:
            if interface_address.family not in _ADDRESS_FAMILIES:
                continue
            address_text = interface_address.address.split(_IPV6_ZONE_SEPARATOR)[0]
            addresses.add(ipaddress.ip_address(address_text).compressed.casefold())
    return frozenset(addresses)


def is_own_address(normalized_hostname: str) -> bool:
    if not isinstance(normalized_hostname, str) or normalized_hostname == "":
        raise TypeError("normalized_hostname must be a non-empty string")
    if normalized_hostname in own_host_names():
        return True
    return normalized_hostname in own_ip_addresses()


def is_from_this_computer(*, client_host: str | None) -> bool:
    """Whether a request came from this computer: from a loopback address, or from one of its own
    network addresses when it opened a vault by that address. Another computer sees only the
    vaults shared on the network (docs/security/README.md, "Sharing on the Network")."""
    if client_host is None:
        return False
    if not isinstance(client_host, str) or client_host == "":
        raise TypeError("client_host must be a non-empty string")
    normalized = client_host.casefold().split(_IPV6_ZONE_SEPARATOR)[0]
    return normalized in own_ip_addresses()
