"""Run the unmodified production launcher in a fresh, disposable deployment."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import requests
import shutil

from tests.support.snapshot import ROOT, copy_production_code


def prepare_deployment(root):
    root.mkdir(parents=True, exist_ok=True)
    copy_production_code(root)
    (root / 'config').mkdir(exist_ok=True)
    (root / 'config/default.json').write_text(json.dumps({
        'memory': {'enabled': True, 'store_backend': 'sqlite_graph', 'neo4j': {'enabled': False}},
        'self_evolve': {'enabled': False},
        'api': {'base_url': 'http://127.0.0.1:9/v1', 'model': 'not-used-at-startup', 'timeout': 1, 'retry_count': 0},
    }), encoding='utf-8')
    (root / 'gateway_config.json').write_text(json.dumps({
        'gateway': {'enabled': True, 'auto_start_channels': True},
        'channels': {'web': {'enabled': True, 'type': 'web'}},
        'computer': {'enabled_controllers': ['filesystem', 'environment']},
    }), encoding='utf-8')
    assert not (root / '.env').exists() and not (root / 'config/users').exists()


def environment(root):
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME', 'PROGRAMFILES', 'PROGRAMFILES(X86)'}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    temp = root / 'temp'
    temp.mkdir(exist_ok=True)
    # Reuse only explicitly supplied local dependency directories, not product imports.
    dependencies = [str(Path(value).resolve()) for value in os.environ.get('PYTHONPATH', '').split(os.pathsep) if value and (ROOT / '.tmp').resolve() in Path(value).resolve().parents]
    env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp), PYTHONPATH=os.pathsep.join([str(root), *dependencies]),
        PYTHONIOENCODING='utf-8', PROMETHEA_SKIP_UI='true', AUTH__SECRET_KEY='disposable-production-test-only',
        SYSTEM__BROWSER_AUTO_INSTALL='false')
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
    if browser_cache and (ROOT / '.tmp').resolve() in Path(browser_cache).resolve().parents:
        env['PLAYWRIGHT_BROWSERS_PATH'] = str(Path(browser_cache).resolve())
    return env


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


@contextmanager
def production_server(root, *, expect_failure=False, port=None):
    port, ui_port = port or free_port(), free_port()
    env = environment(root)
    env.update(PROMETHEA_GATEWAY_PORT=str(port), PROMETHEA_UI_PORT=str(ui_port))
    log_path = root / 'launcher-output.log'
    with log_path.open('a', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, 'start_gateway_service.py'], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            if expect_failure:
                process.wait(timeout=45)
                yield process, log_path
                return
            base = f'http://127.0.0.1:{port}'
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(log_path.read_text(encoding='utf-8', errors='replace')[-10000:])
                try:
                    response = requests.get(base + '/health', timeout=1)
                    if response.ok and response.json().get('gateway_ready'):
                        yield base, log_path
                        return
                except requests.RequestException:
                    pass
                time.sleep(.5)
            raise AssertionError('Production launcher did not become ready: ' + log_path.read_text(encoding='utf-8', errors='replace')[-10000:])
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@contextmanager
def production_ui(root, gateway_url):
    node = shutil.which('node')
    vite = ROOT / 'UI/node_modules/vite/bin/vite.js'
    if not node or not vite.exists():
        raise RuntimeError('Production browser acceptance requires installed UI dependencies and Node')
    port = free_port()
    env = environment(root)
    env['PROMETHEA_GATEWAY_URL'] = gateway_url
    with (root / 'vite-output.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([node, str(vite), '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=ROOT / 'UI', env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            base = f'http://127.0.0.1:{port}'
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError((root / 'vite-output.log').read_text(encoding='utf-8', errors='replace'))
                try:
                    if requests.get(base, timeout=1).ok:
                        yield base
                        return
                except requests.RequestException:
                    pass
                time.sleep(.5)
            raise AssertionError('Production UI did not start')
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
