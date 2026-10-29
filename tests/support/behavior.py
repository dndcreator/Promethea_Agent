"""Production-owned behavior adapters. Synthetic data lives only in the run root."""
import json
from pathlib import Path

from gateway.memory_extraction import classify_interaction, verify_candidates
from gateway.memory_gate import MemoryWriteGate, MemoryWriteRequest
from gateway.protocol import EventType, RequestType
from memory.adapter import MemoryAdapter
from memory.backends.sqlite_graph import SqliteGraphMemoryStore


async def execute_case(case, model, root):
    if case["kind"] == "retrieval":
        store = SqliteGraphMemoryStore(str(root / "memory.db"))
        try:
            for item in case["memories"]:
                store.add_message(session_id="previous", role="user", content=item["text"], user_id=item["user"])
            adapter = MemoryAdapter.__new__(MemoryAdapter)
            adapter.enabled, adapter.store = True, store
            from types import SimpleNamespace
            rows = adapter.collect_recall_candidates(SimpleNamespace(query_text=case["query"], user_id="alice", session_id="current", top_k=8, mode="fast"))
        finally:
            store._conn.close()
        return {"status": "success", "candidates": rows, "evidence": {"recall": rows}, "adapter": "MemoryAdapter/SqliteGraphMemoryStore"}
    if case["kind"] == "classification":
        async def call(_user_id, prompt, query, *, phase):
            result = await model.call_llm([{"role": "system", "content": prompt}, {"role": "user", "content": query}])
            try:
                raw = json.loads(result["content"])
                field = "candidates" if phase == "classifier" else "decisions"
                if not isinstance(raw, dict) or not isinstance(raw.get(field), list):
                    raise ValueError("missing structured " + field)
            except (ValueError, TypeError) as error:
                model.last_error = "Invalid memory model contract: " + str(error)
                raise ValueError(model.last_error) from error
            return result["content"]
        async def classify_call(*args):
            return await call(*args, phase="classifier")
        async def verify_call(*args):
            return await call(*args, phase="verifier")
        classified = await classify_interaction(classify_call, case["user"], case["assistant"], "eval-alice")
        candidates = await verify_candidates(verify_call, "eval-alice", case["user"], case["assistant"], classified["candidates"])
        if getattr(model, "last_error", None):
            raise RuntimeError(model.last_error)
        for row in candidates:
            decision = MemoryWriteGate().evaluate(MemoryWriteRequest(
                source_text=case["user"], proposed_memory_type=row["type"], extracted_content=row["content"],
                confidence=row.get("confidence", 0), modality=row.get("modality", "unknown"), persistence=row.get("persistence", "unknown")))
            row["gate"] = decision.decision
        return {"status": "success", "candidates": candidates, "evidence": {"extraction": candidates}, "adapter": "classify_interaction/verify_candidates/MemoryWriteGate"}
    from tests.support.runtime import runtime_at
    host = runtime_at(root, model)
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="evaluation")
    for name, content in case.get("files", {}).items():
        host.workspace_service.create_document(handle=handle, relative_path=name, content=content, requester_user_id="alice")
    environmental_evidence = {}
    if case["kind"] == "situation":
        from gateway.http.user_file_store import UserFileStore
        from gateway.public_contracts import SemanticSurface
        sources = host.self_model_service.environment_sources
        sources.file_store = UserFileStore(str(root / "user-files"))
        uploaded = sources.file_store.save_upload(user_id="alice", filename="observed.txt", content=case["observed_text"].encode())
        view = SemanticSurface(view="files", surface_id="evaluation", sequence=1, objects=[{"kind": "file", "id": uploaded["file_id"]}])
        await host.self_model_service.environment.observe("alice", view)
        if case.get("closed"):
            await host.self_model_service.environment.observe("alice", view.model_copy(update={"sequence": 2, "visible": False}))
        environmental_evidence["environment"] = await host.self_model_service.environment.snapshot("alice")
    if case["kind"] == "ambient":
        import asyncio
        from gateway.ambient_service import AmbientService
        from gateway.task_runtime import TaskRuntime
        from gateway.public_contracts import AmbientSettings
        from agentkit.tools.ambient import create_tools
        from agentkit.tools.standard.situation_tools import create_situation_tools
        runtime = TaskRuntime(task_service=host.task_service, workflow_engine=host.workflow_engine)
        ambient = AmbientService(conversation=host.conversation_service, task_runtime=runtime, task_service=host.task_service, storage_path=root / "ambient.json")
        host.conversation_service.ambient_service = ambient
        runtime.register_driver("ambient", ambient)
        for tool in [*create_tools({}), *create_situation_tools(host.self_model_service)]:
            host.capability_service.register_tool(tool)
        host.message_manager.create_session("evaluation", user_id="alice")
        ambient.configure("alice", "evaluation", AmbientSettings(enabled=case["enabled"], direction=case["direction"]))
        before = model.budget.calls if model else 0
        try:
            await runtime.recover_incomplete()
            for _ in range(20):
                jobs = list(runtime._jobs.values())
                if not jobs:
                    break
                await asyncio.gather(*jobs)
                await asyncio.sleep(0)
            state = ambient.view("alice", "evaluation")
            events = {f"event:{i}": row.payload for i, row in enumerate(host.event_emitter.get_history(EventType.ACTION_OBSERVATION_COMMITTED))}
            events.update({f"runtime:capabilities:{i}": row.payload for i, row in enumerate(host.event_emitter.get_history(EventType.CAPABILITY_SNAPSHOT_CREATED))})
            tasks = host.task_service.list_tasks(user_id="alice", limit=100)
            runs = [run for task in tasks for run in task["runs"]]
            completed = not case["enabled"] or bool(runs and all(run["status"] == "completed" for run in runs))
            return {"status": "success" if completed else "failed", "tools": [row.get("tool_name") for row in events.values()],
                    "model_calls": (model.budget.calls if model else 0) - before,
                    "answer": json.dumps(host.message_manager.get_messages("evaluation", user_id="alice"), ensure_ascii=False),
                    "evidence": {**events, "ambient": state, "tasks": tasks}, "adapter": "Ambient/TaskRuntime/Conversation/Action/SelfModel"}
        finally:
            await runtime.shutdown()
    response = None
    for turn in case["turns"]:
        response = await host.handle_http_request(method=RequestType.CHAT, params={"message": turn, "session_id": "evaluation"}, user_id="alice")
        if not response.ok or response.payload.get("status") != "success":
            break
    facts = {f"event:{i}": row.payload for i, row in enumerate(host.event_emitter.get_history(EventType.ACTION_OBSERVATION_COMMITTED))}
    facts.update({f"runtime:capabilities:{i}": row.payload for i, row in enumerate(host.event_emitter.get_history(EventType.CAPABILITY_SNAPSHOT_CREATED))})
    tools = [row.get("tool_name") for row in facts.values() if row.get("tool_name")]
    artifacts = {}
    for name in case.get("expect", {}).get("artifacts", {}):
        target = (Path(handle.root_path) / name).resolve()
        if not target.is_relative_to(Path(handle.root_path).resolve()):
            raise ValueError("Evaluation artifact escapes its workspace")
        artifacts[name] = target.read_text(encoding="utf-8") if target.is_file() else None
        facts["file:" + name] = {"content": artifacts[name], "exists": target.is_file()}
    answer = str(response.payload.get("response") or "")
    history = host.message_manager.get_messages("evaluation", user_id="alice")
    return {"status": response.payload.get("status") if response.ok else "error", "answer": answer,
            "tools": tools, "artifacts": artifacts, "evidence": {**facts, **environmental_evidence, "answer": answer},
            "history_matches": bool(history and history[-1]["content"] == answer),
            "adapter": "Gateway/Conversation/Action/Capability/Workspace/SelfModel"}
