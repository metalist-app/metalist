"""A vault not shared on the network leaves no trace on another computer (the maintainer,
2026-11-13): the login page and the vault lists name only the vault it is in and the shared
vaults, and a request naming any other vault is refused the same way whether it exists or not."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.api.routes.auth as auth_route
import app.api.routes.backups as backups_route
import app.security.own_addresses as own_addresses
import app.server_runtime as server_runtime
from app.server_runtime import save_namespace_launch_profile, save_namespace_network_sharing
from app.services.namespace_switcher import namespaces_shown_to_other_computers

THIS_COMPUTER = "10.0.0.76"
WORK_LAPTOP = "10.0.0.99"
NOT_SHARED_MESSAGE = "thomas is not a vault shared on the network. Open it on the computer MetaList runs on."


def _request_from(client_host: str) -> Request:
    return Request({"type": "http", "client": (client_host, 50000), "headers": []})


@pytest.fixture(autouse=True)
def vaults(monkeypatch, tmp_path):
    """cla (the vault the page is in) and work are shared; thomas is not."""
    monkeypatch.setattr(server_runtime, "_DEFAULT_DATABASE_DIRECTORY", tmp_path)
    monkeypatch.setattr(own_addresses, "own_ip_addresses", lambda: frozenset({"127.0.0.1", "::1", THIS_COMPUTER}))
    monkeypatch.setattr(auth_route, "ACTIVE_NAMESPACE", "cla")
    for index, vault in enumerate(("cla", "thomas", "work")):
        save_namespace_launch_profile(namespace=vault, port=9000 + index, https_port=None, mcp_port=None)
    save_namespace_network_sharing(namespace="cla", shared=True)
    save_namespace_network_sharing(namespace="work", shared=True)


def test_another_computer_is_shown_the_current_vault_and_the_shared_ones():
    assert namespaces_shown_to_other_computers(current_namespace="cla") == frozenset({"cla", "work"})


def test_the_current_vault_is_shown_even_when_it_is_not_shared():
    assert namespaces_shown_to_other_computers(current_namespace="thomas") == frozenset({"thomas", "cla", "work"})


def test_the_login_page_on_another_computer_lists_only_those(monkeypatch):
    monkeypatch.setattr(auth_route, "build_login_namespace_catalog", lambda *, current_namespace: {
        "current_namespace": "cla", "namespaces": ["cla", "thomas", "work"],
    })
    remote = auth_route.login_namespace_catalog(request=_request_from(WORK_LAPTOP))
    local = auth_route.login_namespace_catalog(request=_request_from("127.0.0.1"))
    by_address = auth_route.login_namespace_catalog(request=_request_from(THIS_COMPUTER))
    assert remote.namespaces == ["cla", "work"]
    assert local.namespaces == ["cla", "thomas", "work"]
    assert by_address.namespaces == ["cla", "thomas", "work"]


def test_the_vault_list_on_another_computer_names_no_hidden_vault(monkeypatch):
    monkeypatch.setattr(auth_route, "build_namespace_catalog", lambda *, environ, current_namespace: {
        "namespaces": [{"namespace": name} for name in ("cla", "thomas", "work")],
        "reserved_ports": [{"namespace": name, "port": 9000} for name in ("cla", "thomas")],
    })
    catalog = auth_route.namespace_catalog(request=_request_from(WORK_LAPTOP), token="token")
    assert [entry["namespace"] for entry in catalog["namespaces"]] == ["cla", "work"]
    assert [reservation["namespace"] for reservation in catalog["reserved_ports"]] == ["cla"]


@pytest.mark.parametrize("namespace", ["thomas", "never-made"])
def test_another_computer_cannot_open_a_hidden_or_new_vault_and_cannot_tell_which(namespace):
    with pytest.raises(HTTPException) as refusal:
        auth_route.require_vaults_shown_to_requester(request=_request_from(WORK_LAPTOP), namespaces=[namespace])
    assert refusal.value.detail == NOT_SHARED_MESSAGE.replace("thomas", namespace)


def test_this_computer_may_open_any_vault():
    auth_route.require_vaults_shown_to_requester(request=_request_from("127.0.0.1"), namespaces=["thomas", "never-made"])


def test_another_computer_cannot_change_a_hidden_vaults_ports_or_sharing():
    payload = {"profiles": [{"namespace": "thomas", "port": 9001, "https_port": None, "shared_on_network": True}]}
    with pytest.raises(HTTPException) as refusal:
        auth_route.save_namespace_ports.__wrapped__(payload=payload, request=_request_from(WORK_LAPTOP), token="token")
    assert refusal.value.detail == NOT_SHARED_MESSAGE


def test_another_computer_cannot_restore_into_a_hidden_vault():
    payload = backups_route.BackupRestoreRequest(
        backup_id="folder::thomas::thomas-1.metalist-backup.tar.gz", source="folder",
        backup_filename="thomas-1.metalist-backup.tar.gz", backup_namespace="thomas", target_namespace="thomas",
    )
    with pytest.raises(HTTPException) as refusal:
        backups_route.restore_backup.__wrapped__(payload=payload, request=_request_from(WORK_LAPTOP), token="token")
    assert refusal.value.detail == NOT_SHARED_MESSAGE
