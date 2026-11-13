from __future__ import annotations

import asyncio
from collections import namedtuple

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.security.request_boundary import RequestBoundaryMiddleware
from app.security.request_boundary import evaluate_request_boundary
from app.security.request_boundary import resolve_allowed_request_hosts
from app.security import own_addresses
from app.security.request_hosts import binds_to_every_interface


def _build_request(
    *,
    method: str,
    host: str,
    origin: str | None,
    forwarded_host: str | None,
) -> Request:
    headers = [(b"host", host.encode("ascii"))]
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    if forwarded_host is not None:
        headers.append((b"x-forwarded-host", forwarded_host.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "http",
            "path": "/api2/auth/session",
            "raw_path": b"/api2/auth/session",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 9000),
        }
    )


def test_default_request_hosts_are_loopback_only() -> None:
    allowed_hosts = resolve_allowed_request_hosts(environ={}, bind_host="127.0.0.1")

    assert allowed_hosts == frozenset({"127.0.0.1", "::1", "localhost"})


def test_specific_bind_host_is_an_explicit_allowed_host() -> None:
    allowed_hosts = resolve_allowed_request_hosts(environ={}, bind_host="192.168.10.15")

    assert "192.168.10.15" in allowed_hosts


def test_wildcard_bind_requires_explicit_public_host_for_public_requests() -> None:
    allowed_hosts = resolve_allowed_request_hosts(
        environ={"METALIST_ALLOWED_HOSTS": "notes.example.com,notes.internal"},
        bind_host="0.0.0.0",
    )

    assert "0.0.0.0" not in allowed_hosts
    assert "notes.example.com" in allowed_hosts
    assert "notes.internal" in allowed_hosts


@pytest.mark.parametrize(
    "configured_hosts",
    ("*", "https://notes.example.com", "notes.example.com:443", "notes.example.com,,internal"),
)
def test_allowed_host_configuration_rejects_ambiguous_values(configured_hosts: str) -> None:
    with pytest.raises(RuntimeError, match="METALIST_ALLOWED_HOSTS"):
        resolve_allowed_request_hosts(
            environ={"METALIST_ALLOWED_HOSTS": configured_hosts},
            bind_host="127.0.0.1",
        )


def test_dns_rebinding_host_is_rejected_before_origin_validation() -> None:
    rejection = evaluate_request_boundary(
        method="POST",
        request_scheme="http",
        host_header="attacker.example:9000",
        origin_header="http://attacker.example:9000",
        authorization_header=None,
        has_auth_cookie=False,
        allowed_hosts=frozenset({"127.0.0.1", "::1", "localhost"}),
        accepts_own_addresses=False,
    )

    assert rejection is not None
    assert rejection.status_code == 400
    assert rejection.detail == "Unrecognized Host header"


def test_same_origin_state_change_is_allowed() -> None:
    rejection = evaluate_request_boundary(
        method="POST",
        request_scheme="http",
        host_header="127.0.0.1:9000",
        origin_header="http://127.0.0.1:9000",
        authorization_header=None,
        has_auth_cookie=False,
        allowed_hosts=frozenset({"127.0.0.1", "::1", "localhost"}),
        accepts_own_addresses=False,
    )

    assert rejection is None


def test_trusted_https_proxy_scheme_supports_public_same_origin_state_change() -> None:
    rejection = evaluate_request_boundary(
        method="POST",
        request_scheme="https",
        host_header="notes.example.com",
        origin_header="https://notes.example.com",
        authorization_header=None,
        has_auth_cookie=True,
        allowed_hosts=frozenset({"notes.example.com"}),
        accepts_own_addresses=False,
    )

    assert rejection is None


def test_cross_origin_state_change_is_rejected() -> None:
    rejection = evaluate_request_boundary(
        method="PUT",
        request_scheme="http",
        host_header="127.0.0.1:9000",
        origin_header="https://attacker.example",
        authorization_header=None,
        has_auth_cookie=True,
        allowed_hosts=frozenset({"127.0.0.1", "::1", "localhost"}),
        accepts_own_addresses=False,
    )

    assert rejection is not None
    assert rejection.status_code == 403
    assert rejection.detail == "Origin does not match request host"


def test_same_hostname_with_different_origin_port_is_rejected() -> None:
    rejection = evaluate_request_boundary(
        method="POST",
        request_scheme="https",
        host_header="notes.example.com",
        origin_header="https://notes.example.com:8443",
        authorization_header=None,
        has_auth_cookie=True,
        allowed_hosts=frozenset({"notes.example.com"}),
        accepts_own_addresses=False,
    )

    assert rejection is not None
    assert rejection.status_code == 403
    assert rejection.detail == "Origin does not match request host"


@pytest.mark.parametrize("origin", (None, "null"))
def test_cookie_authenticated_state_change_requires_a_real_origin(origin: str | None) -> None:
    rejection = evaluate_request_boundary(
        method="DELETE",
        request_scheme="http",
        host_header="localhost:9000",
        origin_header=origin,
        authorization_header=None,
        has_auth_cookie=True,
        allowed_hosts=frozenset({"127.0.0.1", "::1", "localhost"}),
        accepts_own_addresses=False,
    )

    assert rejection is not None
    assert rejection.status_code == 403


def test_non_browser_bearer_client_may_omit_origin() -> None:
    rejection = evaluate_request_boundary(
        method="PATCH",
        request_scheme="https",
        host_header="notes.example.com",
        origin_header=None,
        authorization_header="Bearer token",
        has_auth_cookie=False,
        allowed_hosts=frozenset({"notes.example.com"}),
        accepts_own_addresses=False,
    )

    assert rejection is None


def test_safe_request_does_not_require_origin() -> None:
    rejection = evaluate_request_boundary(
        method="GET",
        request_scheme="http",
        host_header="localhost:9000",
        origin_header=None,
        authorization_header=None,
        has_auth_cookie=False,
        allowed_hosts=frozenset({"127.0.0.1", "::1", "localhost"}),
        accepts_own_addresses=False,
    )

    assert rejection is None


def test_middleware_ignores_untrusted_forwarded_host() -> None:
    middleware = RequestBoundaryMiddleware(
        lambda scope, receive, send: None,
        allowed_hosts=frozenset({"127.0.0.1", "::1", "localhost"}),
        accepts_own_addresses=False,
    )
    request = _build_request(
        method="POST",
        host="attacker.example:9000",
        origin="http://attacker.example:9000",
        forwarded_host="127.0.0.1:9000",
    )

    async def _call_next(_request: Request) -> Response:
        raise AssertionError("Rejected host must not reach application routes")

    response = asyncio.run(middleware.dispatch(request, _call_next))

    assert response.status_code == 400


# A vault shared on the network accepts the computer's own names and addresses as they are now,
# with nothing listed by hand (docs/security/README.md, "Sharing on the Network").
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
# The two fields of psutil's interface address that the check reads.
_InterfaceAddress = namedtuple("_InterfaceAddress", "family address")


@pytest.fixture
def this_computer(monkeypatch):
    """A computer called Studio-Mac whose router gave it 10.0.0.76 and a link-local IPv6."""
    monkeypatch.setattr(own_addresses.socket, "gethostname", lambda: "Studio-Mac.local")
    addresses = {"en0": [
        _InterfaceAddress(own_addresses.socket.AF_INET, "10.0.0.76"),
        _InterfaceAddress(own_addresses.socket.AF_INET6, "fe80::1c2b:3a4d%en0"),
    ], "lo0": [
        _InterfaceAddress(own_addresses.socket.AF_INET, "127.0.0.1"),
    ]}
    monkeypatch.setattr(own_addresses.psutil, "net_if_addrs", lambda: addresses)
    return addresses


def _boundary_for_host(host_header: str, *, accepts_own_addresses: bool):
    return evaluate_request_boundary(
        method="POST",
        request_scheme="https",
        host_header=host_header,
        origin_header=f"https://{host_header}",
        authorization_header=None,
        has_auth_cookie=True,
        allowed_hosts=_LOOPBACK_HOSTS,
        accepts_own_addresses=accepts_own_addresses,
    )


@pytest.mark.parametrize("host_header", ("10.0.0.76:9443", "studio-mac.local:9443", "Studio-Mac.local:9443", "[fe80::1c2b:3a4d]:9443"))
def test_a_shared_vault_accepts_the_computers_own_names_and_addresses(this_computer, host_header) -> None:
    assert _boundary_for_host(host_header, accepts_own_addresses=True) is None


def test_a_new_address_from_the_router_is_accepted_without_a_restart(this_computer) -> None:
    assert _boundary_for_host("10.0.0.31:9443", accepts_own_addresses=True) is not None
    this_computer["en0"][0] = this_computer["en0"][0]._replace(address="10.0.0.31")
    assert _boundary_for_host("10.0.0.31:9443", accepts_own_addresses=True) is None
    assert _boundary_for_host("10.0.0.76:9443", accepts_own_addresses=True) is not None


@pytest.mark.parametrize("host_header", ("attacker.example:9443", "10.0.0.99:9443", "other-mac.local:9443"))
def test_a_shared_vault_still_refuses_names_that_are_not_its_own(this_computer, host_header) -> None:
    rejection = _boundary_for_host(host_header, accepts_own_addresses=True)
    assert rejection is not None
    assert rejection.detail == "Unrecognized Host header"


def test_a_vault_not_shared_accepts_only_loopback(this_computer) -> None:
    rejection = _boundary_for_host("10.0.0.76:9443", accepts_own_addresses=False)
    assert rejection is not None
    assert rejection.detail == "Unrecognized Host header"
    assert _boundary_for_host("127.0.0.1:9443", accepts_own_addresses=False) is None


def test_only_a_server_listening_everywhere_accepts_its_own_addresses() -> None:
    assert binds_to_every_interface(bind_host="0.0.0.0") is True
    assert binds_to_every_interface(bind_host="::") is True
    assert binds_to_every_interface(bind_host="127.0.0.1") is False
    assert binds_to_every_interface(bind_host="192.168.10.15") is False
