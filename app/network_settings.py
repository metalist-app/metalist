"""Retires network-settings.json, the hand-kept file that once said where MetaList listened.

Each vault now says for itself whether it is shared on the network (Manage Vault Ports), and a
shared vault accepts the computer's own names and addresses as they are now
(app/security/own_addresses.py). On the first start that finds the old file, every vault it
shared stays shared, and the file is removed. A name it allowed that is not one of the
computer's own (a domain behind a proxy) belongs in METALIST_ALLOWED_HOSTS in the environment
that starts MetaList, so the start stops and says so rather than dropping it.
"""
from __future__ import annotations

from collections.abc import Mapping
import ipaddress
import json
from pathlib import Path

from app.data_directory import resolve_data_directory
from app.security.own_addresses import own_host_names
from app.security.request_hosts import _normalize_configured_hostname
from app.security.shell_execution import is_loopback_host
from app.server_runtime import load_all_namespace_launch_profiles, save_namespace_network_sharing
from app.services.exception_capture import CapturedExceptionContext

NETWORK_SETTINGS_FILE_NAME = 'network-settings.json'
_NETWORK_ENVIRONMENT_KEYS = frozenset({'METALIST_HOST', 'METALIST_ALLOWED_HOSTS'})
_NETWORK_SETTINGS_VERSION = 1


def _read_network_settings(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(payload, dict) or set(payload) != {'version', 'environment'}
            or type(payload['version']) is not int or payload['version'] != _NETWORK_SETTINGS_VERSION):
        raise RuntimeError(f'Invalid network settings file: {path}')
    environment = payload['environment']
    if not isinstance(environment, dict) or not environment.keys() <= _NETWORK_ENVIRONMENT_KEYS:
        raise RuntimeError(f'{path} must contain only METALIST_HOST and METALIST_ALLOWED_HOSTS')
    if any(not isinstance(value, str) for value in environment.values()):
        raise RuntimeError(f'{path} values must be strings')
    return dict(environment)


def _is_ip_address(normalized_hostname: str) -> bool:
    ip_capture = CapturedExceptionContext(ValueError, boundary='app/network_settings.py:_is_ip_address:ip_capture')
    with ip_capture:
        ipaddress.ip_address(normalized_hostname)
    return ip_capture.captured_exception is None


def names_kept_by_hand(*, allowed_hosts: str) -> list[str]:
    """The allowed names that are neither an address (any address of this computer is accepted
    now, whichever the router gave it) nor one of the computer's own names."""
    own_names = own_host_names()
    kept: list[str] = []
    for raw_host in allowed_hosts.split(','):
        normalized = _normalize_configured_hostname(raw_value=raw_host)
        if _is_ip_address(normalized) or normalized in own_names:
            continue
        kept.append(normalized)
    return kept


def retire_network_settings_file(*, environ: Mapping[str, str]) -> None:
    path = resolve_data_directory(environ=environ) / NETWORK_SETTINGS_FILE_NAME
    if not path.exists():
        return
    saved = _read_network_settings(path)
    if 'METALIST_ALLOWED_HOSTS' in saved:
        kept = names_kept_by_hand(allowed_hosts=saved['METALIST_ALLOWED_HOSTS'])
        if kept:
            raise RuntimeError(
                f'{path} allows {", ".join(kept)}, and MetaList no longer reads that file. '
                f'Set METALIST_ALLOWED_HOSTS={",".join(kept)} where MetaList is started, then remove the file.'
            )
    shared = 'METALIST_HOST' in saved and not is_loopback_host(host=saved['METALIST_HOST'])
    if shared:
        namespaces = [profile.namespace for profile in load_all_namespace_launch_profiles()]
        for namespace in namespaces:
            save_namespace_network_sharing(namespace=namespace, shared=True)
        print(f'[startup] Shared on the network, as before: {", ".join(namespaces)}', flush=True)
    path.unlink()
    print(f'[startup] Removed {path}: each vault now says whether it is shared (Manage Vault Ports).', flush=True)
