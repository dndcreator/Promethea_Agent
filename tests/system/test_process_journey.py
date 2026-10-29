"""TCP -> real HTTP/Gateway/services/tools -> disk -> actual process restart."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import requests
from tests.support.snapshot import copy_code


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def serving(code, data):
    endpoint = data / "endpoint.json"
    endpoint.unlink(missing_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("API__", "MULTIMODAL__", "MEMORY__", "PROMETHEA_EVAL_"))}
    env.update(PYTHONPATH=str(code), MEMORY__ENABLED="false", MEMORY__NEO4J__ENABLED="false", PROMETHEA_TEST="1", SELF_EVOLVE__ENABLED="false")
    with (data / "server.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "tests.support.http_host", "--root", str(data)], cwd=code, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError((data / "server.log").read_text(encoding="utf-8", errors="replace")[-4000:])
                if endpoint.exists():
                    base = "http://127.0.0.1:" + str(json.loads(endpoint.read_text())["port"])
                    try:
                        if requests.get(base + "/openapi.json", timeout=1).status_code == 200:
                            yield base
                            return
                    except requests.RequestException:
                        pass
                time.sleep(0.1)
            raise AssertionError("Isolated HTTP host did not become ready within 45 seconds")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_external_client_artifact_and_history_survive_process_restart(tmp_path):
    code, data = tmp_path / "code", tmp_path / "data"
    code.mkdir()
    data.mkdir()
    copy_code(code)
    script = [
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "net.txt", "content": "NET=32"}},
        {"action": "tool_call", "tool_name": "workspace.read_file", "args": {"path": "net.txt"}}, "$observation",
    ]
    (data / "model.json").write_text(json.dumps(script))
    with serving(code, data) as base, requests.Session() as client:
        login = client.post(base + "/api/auth/login", json={"username": "acceptance", "password": "isolated-password"}, timeout=10)
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        result = client.post(base + "/api/chat", json={"message": "Write and verify net.txt", "session_id": "report", "stream": True}, timeout=30)
        assert "event: done" in result.text and "event: error" not in result.text, result.text[-2000:]
        assert (data / "workspaces/alice/report/net.txt").read_text() == "NET=32"
        history = client.get(base + "/api/sessions/report", timeout=10).json()["messages"]
    (data / "model.json").write_text("[]")
    with serving(code, data) as base:
        response = requests.get(base + "/api/sessions/report", headers={"Authorization": "Bearer " + token}, timeout=10)
        assert response.status_code == 200 and response.json()["messages"] == history
        assert (data / "workspaces/alice/report/net.txt").read_text() == "NET=32"
