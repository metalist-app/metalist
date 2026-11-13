"""network-settings.json is retired (docs/security/README.md, "Sharing on the Network"): each
vault says for itself whether it is shared, and a shared vault accepts the computer's own names
and addresses as they are now. The first start that finds the old file keeps every vault it
shared shared, and removes it."""
import json

import pytest

import app.server_runtime as server_runtime
from app import network_settings
from app.network_settings import retire_network_settings_file
from app.server_runtime import load_namespace_network_sharing, save_namespace_launch_profile

VAULTS = ('thomas', 'cla')


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """A data root with two vaults, neither shared yet, on a computer called Studio-Mac."""
    monkeypatch.setattr(server_runtime, '_DEFAULT_DATABASE_DIRECTORY', tmp_path)
    monkeypatch.setattr(network_settings, 'own_host_names', lambda: frozenset({'studio-mac.local'}))
    for index, vault in enumerate(VAULTS):
        save_namespace_launch_profile(namespace=vault, port=9000 + index, https_port=None, mcp_port=None)
    return tmp_path


def _write_settings(data_root, environment):
    path = data_root / 'network-settings.json'
    path.write_text(json.dumps({'version': 1, 'environment': environment}))
    return path


def test_every_vault_the_old_file_shared_stays_shared_and_the_file_is_removed(data_root):
    path = _write_settings(data_root, {'METALIST_HOST': '0.0.0.0', 'METALIST_ALLOWED_HOSTS': '10.0.0.31'})
    retire_network_settings_file(environ={'METALIST_DATA_DIRECTORY': str(data_root)})
    assert [load_namespace_network_sharing(namespace=vault) for vault in VAULTS] == [True, True]
    assert not path.exists()


def test_a_file_that_kept_metalist_on_this_computer_shares_nothing(data_root):
    path = _write_settings(data_root, {'METALIST_HOST': '127.0.0.1'})
    retire_network_settings_file(environ={'METALIST_DATA_DIRECTORY': str(data_root)})
    assert [load_namespace_network_sharing(namespace=vault) for vault in VAULTS] == [False, False]
    assert not path.exists()


def test_without_the_file_nothing_changes(data_root):
    retire_network_settings_file(environ={'METALIST_DATA_DIRECTORY': str(data_root)})
    assert [load_namespace_network_sharing(namespace=vault) for vault in VAULTS] == [False, False]


def test_addresses_and_the_computers_own_name_need_no_list_any_more(data_root):
    path = _write_settings(data_root, {
        'METALIST_HOST': '0.0.0.0', 'METALIST_ALLOWED_HOSTS': '10.0.0.31,Studio-Mac.local,fe80::1',
    })
    retire_network_settings_file(environ={'METALIST_DATA_DIRECTORY': str(data_root)})
    assert not path.exists()


def test_a_name_kept_by_hand_stops_the_start_and_keeps_the_file(data_root):
    original = {'METALIST_HOST': '0.0.0.0', 'METALIST_ALLOWED_HOSTS': '10.0.0.31,notes.example.com'}
    path = _write_settings(data_root, original)
    with pytest.raises(RuntimeError, match='METALIST_ALLOWED_HOSTS=notes.example.com'):
        retire_network_settings_file(environ={'METALIST_DATA_DIRECTORY': str(data_root)})
    assert json.loads(path.read_text())['environment'] == original
    assert [load_namespace_network_sharing(namespace=vault) for vault in VAULTS] == [False, False]


@pytest.mark.parametrize('payload', [
    '{', '[]', '{"version": 2, "environment": {}}',
    json.dumps({'version': 1, 'environment': {'METALIST_SHELL_ENABLED': '1'}}),
    json.dumps({'version': 1, 'environment': {'METALIST_HOST': None}}),
])
def test_a_corrupt_file_fails_instead_of_silently_changing_where_vaults_listen(data_root, payload):
    path = data_root / 'network-settings.json'
    path.write_text(payload)
    with pytest.raises((ValueError, RuntimeError)):
        retire_network_settings_file(environ={'METALIST_DATA_DIRECTORY': str(data_root)})
    assert path.read_text() == payload
