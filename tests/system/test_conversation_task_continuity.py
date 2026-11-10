"""Public chat and Task Runtime with a real disk checkpoint and scripted model I/O."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

import httpx
import pytest
import requests

from gateway.http.routes import auth
from tests.support.http_runtime import app_at
from tests.support.production import prepare_deployment, production_server
from tests.support.runtime import ScriptedModel, observation_fact


def call(name, **args):
    return {"action": "tool_call", "tool_name": name, "args": args}

def answer(content):
    return {"action": "answer", "content": content}


def browser(app, user="alice"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                             headers={"Authorization": "Bearer " + auth.create_access_token({"sub": user})})


async def chat(client, session, message, *, stream=False):
    response = await client.post("/api/chat", json={"session_id": session, "message": message, "stream": stream})
    response.raise_for_status()
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        return next(event for event in events if event["type"] == "done")["content"]
    return response.json()["response"]


async def settled(client, task_id, status):
    for _ in range(150):
        task = (await client.get(f"/api/tasks/{task_id}")).raise_for_status().json()["task"]
        if task["runs"][0]["status"] == status:
            return task
        if task["runs"][0]["status"] in {"failed", "cancelled"}:
            pytest.fail(str(task))
        await asyncio.sleep(.02)
    pytest.fail(f"Task never reached {status}: {task}")


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
async def test_chat_handoff_restart_and_resume_from_another_chat(tmp_path, monkeypatch, stream):
    def task_write(messages):
        assert "Plan my commute" in str(messages)
        return call("workspace.write_file", path="location.txt", content="Fengtai / Evidence 91")

    first = ScriptedModel([call("task.start", title="Morning commute"), answer("Started the task."), task_write,
                           {"status": "error", "code": "MODEL_ADMISSION_CLOSED", "error": "Fixture admission closed"}])
    app, host = app_at(tmp_path, first, monkeypatch, durable_chat=True)
    settings = host.config_service.get_merged_config("alice")
    settings["action"].update(max_steps=2, progress_grace_steps=0)
    with monkeypatch.context() as changes:
        changes.setattr(host.config_service, "get_merged_config", lambda _: settings)
        async with browser(app) as client:
            assert await chat(client, "origin", "Plan my commute", stream=stream) == "Started the task."
            rows = (await client.get("/api/tasks")).json()["tasks"]
            assert len(rows) == 1
            task_id = rows[0]["task_id"]
            paused = await settled(client, task_id, "paused")
            run_id = paused["runs"][0]["run_id"]
            assert paused["session_ids"] == ["origin"]
        await host.task_runtime.shutdown()

    def match_task(messages):
        match, = observation_fact(messages)["result"]["tasks"]
        assert match["task_id"] == task_id and match["run_id"] == run_id
        return call("task.resume", task_id=match["task_id"])

    def continue_work(messages):
        assert "Fengtai / Evidence 91" in str(messages)
        assert "Continue my commute task" not in str(messages)
        return call("workspace.read_file", path="location.txt")

    def finish(messages):
        fact = observation_fact(messages)
        assert fact["status"] == "completed", fact
        assert fact["result"]["content"] == "Fengtai / Evidence 91"
        return answer("Verified the original workspace evidence.")

    second = ScriptedModel([call("task.list"), match_task, answer("Resumed the same task."), continue_work, finish])
    app, reopened = app_at(tmp_path, second, monkeypatch, durable_chat=True)
    try:
        async with browser(app) as client:
            assert await chat(client, "followup", "Continue my commute task", stream=stream) == "Resumed the same task."
            finished = await settled(client, task_id, "completed")
            assert finished["session_ids"] == ["origin", "followup"]
            assert finished["runs"][0]["run_id"] == run_id
            assert finished["runs"][0]["session_id"] == "origin"
            assert finished["runs"][0]["output"] == "Verified the original workspace evidence."
            assert len((await client.get("/api/tasks")).json()["tasks"]) == 1
        async with browser(app, "bob") as other:
            assert (await other.get(f"/api/tasks/{task_id}")).status_code == 404
        origin = reopened.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="origin")
        followup = reopened.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="followup")
        assert (Path(origin.root_path) / "location.txt").is_file()
        assert not (Path(followup.root_path) / "location.txt").exists()
        facts = reopened.event_emitter.event_log.query(task_id=task_id, event_type="action.observation.committed")
        assert sum(row["payload"]["tool_name"] == "workspace.write_file" for row in facts) == 1
        assert sum(row["payload"]["tool_name"] == "workspace.read_file" for row in facts) == 1
    finally:
        await reopened.task_runtime.shutdown()


@pytest.mark.asyncio
async def test_direct_chat_does_not_create_a_task(tmp_path, monkeypatch):
    app, host = app_at(tmp_path, ScriptedModel([answer("Four.")]), monkeypatch, durable_chat=True)
    async with browser(app) as client:
        assert await chat(client, "quick", "What is two plus two?") == "Four."
        assert (await client.get("/api/tasks")).json()["tasks"] == []
    await host.task_runtime.shutdown()


@pytest.mark.asyncio
async def test_generic_resume_is_not_tool_approval(tmp_path, monkeypatch):
    executed = []

    class SensitiveTool:
        name = tool_id = "fixture.send"
        side_effect_level = "external_write"
        description = "Record an approved test operation"
        input_schema = {"type": "object", "properties": {}}

        async def invoke(self, args, ctx=None):
            executed.append(ctx.session_id)
            return {"recorded": True}

    def resume_proposal(messages):
        task, = observation_fact(messages)["result"]["tasks"]
        return call("task.resume", task_id=task["task_id"])

    model = ScriptedModel([call("task.start", title="Send draft"), answer("Started."),
                           call("fixture.send"), call("task.list"), resume_proposal,
                           answer("The task still needs approval."), answer("Recorded once.")])
    app, host = app_at(tmp_path, model, monkeypatch, durable_chat=True)
    host.capability_service.register_tool(SensitiveTool())
    try:
        async with browser(app) as client:
            await chat(client, "origin", "Prepare and send the draft")
            task_id = (await client.get("/api/tasks")).json()["tasks"][0]["task_id"]
            waiting = await settled(client, task_id, "waiting_human")
            run, = waiting["runs"]
            await chat(client, "other-chat", "Continue the draft task")
            assert (await settled(client, task_id, "waiting_human"))["session_ids"] == ["origin", "other-chat"]
            assert executed == []
            endpoint = f"/api/tasks/{task_id}/confirm"
            approval = {"run_id": run["run_id"], "tool_call_id": run["pending_confirmation"]["tool_call_id"], "action": "approve"}
            async with browser(app, "bob") as other:
                assert (await other.post(endpoint, json=approval)).status_code == 404
            assert (await client.post(endpoint, json={**approval, "tool_call_id": "wrong"})).status_code == 409
            assert executed == []
            assert (await client.post(endpoint, json=approval)).status_code == 200
            final = await settled(client, task_id, "completed")
            assert final["runs"][0]["output"] == "Recorded once."
            assert (await client.post(endpoint, json=approval)).status_code == 409
            assert executed == ["origin"]
    finally:
        await host.task_runtime.shutdown()


def test_production_native_task_resumes_after_process_restart(tmp_path):
    evidence = "PRODUCTION-COMMUTE-77"

    def pick_task(messages):
        receipt = json.loads(next(row["content"] for row in reversed(messages) if row["role"] == "tool"))
        tasks = receipt["observations"][0]["result"]["tasks"]
        assert len(tasks) == 1 and tasks[0]["run_status"] == "paused"
        return call("task.resume", task_id=tasks[0]["task_id"])

    def verify(messages):
        assert evidence in str(messages)
        return call("workspace.read_file", path="map-evidence.txt")

    def finish(messages):
        receipt = json.loads(next(row["content"] for row in reversed(messages) if row["role"] == "tool"))
        assert receipt["observations"][0]["result"]["content"] == evidence
        return answer("Verified the saved location.")

    actions = iter([call("task.start", title="Plan commute"), answer("Task started."),
                    call("workspace.write_file", path="map-evidence.txt", content=evidence), None,
                    call("task.list"), pick_task, answer("Task continued."), verify, finish])
    provider_errors = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                value = next(actions)
                if callable(value):
                    value = value(request["messages"])
                if value is None:
                    status, packet = 403, {"error": {"code": "EVALUATION_ADMISSION_CLOSED", "message": "fixture stop"}}
                else:
                    message = {"role": "assistant", "content": value.get("content")}
                    if value["action"] == "tool_call":
                        message["tool_calls"] = [{"id": f"call_{self.server.next_id}", "type": "function",
                                                  "function": {"name": "tool_call", "arguments": json.dumps(
                                                      {k: v for k, v in value.items() if k != "action"})}}]
                    self.server.next_id += 1
                    status, packet = 200, {"id": "fixture", "created": 0, "object": "chat.completion", "model": "fixture",
                                           "choices": [{"index": 0, "message": message,
                                                        "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                                           "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
            except Exception as exc:
                provider_errors.append(repr(exc))
                status, packet = 500, {"error": {"message": "fixture assertion failed"}}
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(packet).encode())

    def wait_for(client, base, task_id, expected):
        deadline = monotonic() + 20
        while monotonic() < deadline:
            response = client.get(f"{base}/api/tasks/{task_id}", timeout=5)
            response.raise_for_status()
            task = response.json()["task"]
            if task["runs"][0]["status"] == expected:
                return task
            assert task["runs"][0]["status"] != "failed", (task, provider_errors)
            sleep(.1)
        pytest.fail(f"Task never reached {expected}: {task}, {provider_errors}")

    root = tmp_path / "deployment"
    prepare_deployment(root)
    config_path = root / "config/default.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server.next_id = 1
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config["memory"]["enabled"] = False
        config["api"].update(base_url=f"http://127.0.0.1:{server.server_port}/v1", api_key="fixture",
                             model="fixture", tool_protocol="native", timeout=10)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        credentials = {"username": "commute-test", "password": "fixture-password"}
        with requests.Session() as client:
            for index, (session, prompt) in enumerate((("origin", "Plan my commute"), ("followup", "Continue my commute task"))):
                with production_server(root) as (base, _):
                    if index == 0:
                        client.post(base + "/api/auth/register", json=credentials, timeout=10).raise_for_status()
                    login = client.post(base + "/api/auth/login", json=credentials, timeout=10)
                    login.raise_for_status()
                    client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
                    response = client.post(base + "/api/chat", json={"session_id": session, "message": prompt, "stream": False}, timeout=20)
                    assert response.ok, (response.text, provider_errors)
                    listed = client.get(base + "/api/tasks", timeout=10)
                    listed.raise_for_status()
                    task, = listed.json()["tasks"]
                    if index == 0:
                        task_id, run_id = task["task_id"], task["runs"][0]["run_id"]
                        wait_for(client, base, task_id, "paused")
                    else:
                        assert task["task_id"] == task_id
                        completed = wait_for(client, base, task_id, "completed")
                        assert completed["session_ids"] == ["origin", "followup"]
                        assert completed["runs"][0]["run_id"] == run_id
                        assert completed["runs"][0]["output"] == "Verified the saved location."
        assert not provider_errors and next(actions, False) is False
        origin_files = list((root / "workspace").glob("*/origin/map-evidence.txt"))
        assert len(origin_files) == 1 and origin_files[0].read_text() == evidence
        assert not list((root / "workspace").glob("*/followup/map-evidence.txt"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
