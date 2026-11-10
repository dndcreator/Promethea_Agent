"""Compare action context reconstruction against the existing projector, offline."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentkit.tools.standard.runtime_tools import RuntimeListObservationsTool, RuntimeReadObservationTool
from config import ActionConfig
from gateway.action.context_window import CONTEXT_ANCHOR, compact_action_history
from gateway.action.observation import RuntimeObservation
from gateway.action.service import ActionService
from gateway.capability_service import ToolInvocationContext
from gateway.model_protocol import request_fields, response_fields
from gateway.protocol import EventType
from gateway.runtime_event_log import RuntimeEventLog
from gateway.runtime_io import ContextCompiler


def fixture(step):
    return RuntimeObservation(action_loop_id="offline", model_step_id=f"step{step}", tool_call_id=f"call{step}",
        observation_id=f"obs{step:03d}", tool_name="fixture.inspect", ok=step != 6,
        structured_result=None if step == 6 else {
            "path": f"reports/check-{step:02d}.txt", "check": f"checkpoint-{step:02d}-exact", "reading": step * 137 + 19,
            "body": (f"payload for step {step}: delta verified against source record.\n" * (35 + step % 5)),
        }, error={"code": "FIXTURE_TIMEOUT", "category": "timeout", "message": "timed out after 173 ms"} if step == 6 else None)


def measure(request, observations):
    facts, index = {}, {}
    for message in request["messages"]:
        if message["role"] == "tool":
            facts.update((row["observation_id"], row) for row in json.loads(message["content"])["observations"])
        elif message.get("name") == CONTEXT_ANCHOR:
            index = {row["id"]: row for row in json.loads(message["content"].split("\n", 1)[1])["recent_archived_evidence"]}
    direct, statuses, paths = 0, 0, 0
    for row in observations:
        fact = facts.get(row.observation_id, {})
        indexed = index.get(row.observation_id, {})
        statuses += fact.get("status") == ("completed" if row.ok else "failed") or indexed.get("ok") is row.ok
        if row.ok:
            result = fact.get("result") or {}
            result = result.get("summary", result)
            paths += (result.get("path") or indexed.get("path")) == row.structured_result["path"]
            direct += (result.get("check"), result.get("reading")) == (row.structured_result["check"], row.structured_result["reading"])
        else:
            direct += all((fact.get("error") or {}).get(key) == row.error[key] for key in ("code", "message"))
    size = len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return {"request_bytes": size, "direct_details": direct, "exact_statuses": statuses, "exact_paths": paths,
            "latest_detail_exact": (facts.get(observations[-1].observation_id) or {}).get("result") == observations[-1].structured_result}


async def evaluate(output):
    policy = ActionConfig()
    goal = "Verify the files, preserve exact readings, and explain any failure."
    baseline = rebuilt = [{"role": "system", "content": "Fixture system policy."}, {"role": "user", "content": goal}]
    observations, wire, samples, rebuild_steps = [], {}, [], []
    log = RuntimeEventLog(storage_path=str(output / "evidence.jsonl"))
    for step in range(1, 31):
        obs = fixture(step)
        observations.append(obs)
        packet = {"role": "assistant", "tool_calls": [{"id": obs.tool_call_id, "type": "function", "function": {
            "name": "tool_call", "arguments": json.dumps({"tool_name": obs.tool_name, "args": {"step": step}}),
        }}]}
        accepted = response_fields(packet)
        wire[obs.model_step_id] = {"message": packet, "bindings": accepted["native_bindings"]}
        pair = ActionService._observation_messages(accepted["content"], [obs], model_step_id=obs.model_step_id)
        original = [row.as_dict() for row in observations]
        log.append(event_type=EventType.ACTION_OBSERVATION_COMMITTED.value, payload={**original[-1], "user_id": "offline", "session_id": "replay"})
        baseline = [*baseline, *pair]
        rebuilt, changed = compact_action_history([*rebuilt, *pair], original,
            max_chars=min(policy.context_action_chars, policy.observation_history_chars), max_batches=policy.context_action_batches,
            per_result_chars=policy.observation_chars, goal=goal)
        if changed:
            rebuild_steps.append(step)
        baseline, rebuilt = [ContextCompiler.project_observations(history, original,
            per_result_chars=policy.observation_chars, total_chars=policy.observation_history_chars) for history in (baseline, rebuilt)]
        options = {"protocol": "native", "purpose": "action", "wire_history": wire, "observations": original}
        samples.append({"step": step, "baseline": measure(request_fields(baseline, options), observations),
                        "rebuilt": measure(request_fields(rebuilt, options), observations)})

    server = SimpleNamespace(event_emitter=SimpleNamespace(event_log=log))
    scope = ToolInvocationContext(user_id="offline", session_id="replay")
    index, reader = RuntimeListObservationsTool(gateway_server=server), RuntimeReadObservationTool(gateway_server=server)
    cursor, recovered = 0, []
    while cursor is not None:
        page = await index.invoke({"after_seq": cursor, "limit": 10}, scope)
        for row in page["observations"]:
            obs = next(item for item in observations if item.observation_id == row["observation_id"])
            result = await reader.invoke({"observation_id": obs.observation_id, "field": "result" if obs.ok else "error"}, scope)
            if json.loads(result["content"]) == (obs.structured_result if obs.ok else obs.error):
                recovered.append(obs.observation_id)
        cursor = page["next_after_seq"]
    return {"provider_calls": 0, "rebuild_steps": rebuild_steps, "exact_readback": len(recovered),
            "total_observations": len(observations), "per_step": samples}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    destination = parser.parse_args().output.resolve()
    if not destination.is_relative_to((ROOT / ".tmp").resolve()):
        parser.error("use a fresh output directory under .tmp")
    destination.mkdir(parents=True)
    report = asyncio.run(evaluate(destination))
    (destination / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({**{key: value for key, value in report.items() if key != "per_step"},
                      "selected": [row for row in report["per_step"] if row["step"] in {1, 12, 13, 20, 30}]}, indent=2))
