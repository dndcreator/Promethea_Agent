"""Actual launcher, lifespan, plugin discovery, service wiring and persistent stores."""
import requests
import pytest

from tests.support.production import prepare_deployment, production_server


def test_production_launcher_login_file_content_and_restart(tmp_path):
    root = tmp_path / 'deployment'
    prepare_deployment(root)
    with production_server(root) as (base, log):
        health = requests.get(base + '/health', timeout=5).json()
        assert health['agent_ready'] and health['gateway_ready'] and health['startup_status'] != 'failed'
        created = requests.post(base + '/api/auth/register', json={'username': 'deployment-test', 'password': 'test-only-password'}, timeout=10)
        assert created.status_code == 200, created.text
        login = requests.post(base + '/api/auth/login', json={'username': 'deployment-test', 'password': 'test-only-password'}, timeout=10)
        assert login.status_code == 200, login.text
        token = login.json()['access_token']
        headers = {'Authorization': 'Bearer ' + token}
        uploaded = requests.post(base + '/api/files/upload', headers=headers, files={'file': ('report.txt', b'ORCHID-29', 'text/plain')}, timeout=10)
        assert uploaded.status_code == 200, uploaded.text
        file_id = uploaded.json().get('file', uploaded.json())['file_id']
        # Dispatch the real registered tool through the public batch/Gateway boundary.
        command = {'requests': [{'method': 'tool.call', 'params': {'tool_name': 'environment.inspect', 'params': {'resource': {'kind': 'file', 'id': file_id}}}}]}
        inspected = requests.post(base + '/api/batch', headers=headers, json=command, timeout=10)
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()['results'][0]['ok'], inspected.text
        assert 'ORCHID-29' in inspected.text
        text = log.read_text(encoding='utf-8', errors='replace')
        assert 'Gateway system initialized successfully' in text
        assert 'Gateway ready at' in text and 'environment source already registered' not in text
    with production_server(root) as (base, _):
        assert requests.post(base + '/api/auth/login', json={'username': 'deployment-test', 'password': 'test-only-password'}, timeout=10).status_code == 200
        inspected = requests.post(base + '/api/batch', headers=headers, json=command, timeout=10)
        assert inspected.status_code == 200 and 'ORCHID-29' in inspected.text


@pytest.mark.parametrize('fault,error', [('config', 'JSONDecodeError'), ('workspace', 'FileExistsError')])
def test_production_launcher_failure_exits_without_false_ready_or_polling(tmp_path, fault, error):
    root = tmp_path / 'deployment'
    prepare_deployment(root)
    if fault == 'config':
        (root / 'gateway_config.json').write_text('{invalid json', encoding='utf-8')
    else:
        (root / 'workspace').write_text('a file blocks required workspace-directory creation', encoding='utf-8')
    with production_server(root, expect_failure=True) as (process, log):
        assert process.returncode != 0
        text = log.read_text(encoding='utf-8', errors='replace')
        assert error in text
        assert 'Gateway startup failed' in text
        assert 'Gateway integration initialized' not in text
        assert 'Kernel scheduler started' not in text
        assert 'GET /health' not in text and 'Timed out waiting' not in text
