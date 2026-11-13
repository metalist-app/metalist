from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import os


SHELL_EXECUTION_ENV_NAME = "METALIST_SHELL_ENABLED"


def is_loopback_host(*, host: str) -> bool:
    if not isinstance(host, str) or host.strip() == "":
        raise TypeError("host must be a non-empty string")
    normalized_host = host.strip().casefold()
    if normalized_host.startswith("[") and normalized_host.endswith("]"):
        normalized_host = normalized_host[1:-1]
    return normalized_host in {"127.0.0.1", "::1", "localhost"}


def enable_shell_execution_for_launch(*, environ: MutableMapping[str, str]) -> None:
    # Where each vault listens is its own choice (app/server_runtime.resolve_vault_bind_host);
    # shell routes answer only loopback clients asking a loopback host either way.
    environ[SHELL_EXECUTION_ENV_NAME] = "1"


def is_shell_execution_enabled_for_environ(
    *,
    environ: Mapping[str, str],
) -> bool:
    if SHELL_EXECUTION_ENV_NAME not in environ:
        return False
    raw_value = environ[SHELL_EXECUTION_ENV_NAME]
    if raw_value != "1":
        raise RuntimeError(f"{SHELL_EXECUTION_ENV_NAME} must be '1' when set")
    return True


def is_shell_execution_enabled() -> bool:
    return is_shell_execution_enabled_for_environ(environ=os.environ)
