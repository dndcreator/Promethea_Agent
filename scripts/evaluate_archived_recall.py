"""Blind archived-evidence test: scripted staging, real Runtime, one metered model run."""
import argparse
import asyncio
import json
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openai import AsyncOpenAI
from agentkit.tools.standard.runtime_tools import RuntimeListObservationsTool, RuntimeReadObservationTool
from conversation_core import PrometheaConversation
from gateway.action import ActionService
from gateway.action.context_window import CONTEXT_ANCHOR
from gateway.capability_service import ToolInvocationContext
from gateway.events import EventEmitter
from gateway.model_protocol import request_fields, response_fields
from gateway.runtime_event_log import RuntimeEventLog
from gateway.runtime_io import ContextCompiler
from gateway.tool_prompt_blocks import build_action_protocol_prompt
from tests.support.metered_proxy import MeteredProxy
from tests.support.runtime_efficiency import eval_settings

OWNER, SESSION = "archive-evaluation", "fiction"
GOAL = "Review the production notes for the original fiction 'The Lantern Archive'."
QUESTION = ("In the initial gate incident, what exact phrase opened the inner gate, and who entered it? "
            "Report the original phrase verbatim and cite the Runtime evidence you verified. Do not guess.")
STEPS = 21
POLICY = {"api": {"max_tokens": 2048, "output_token_limit": 2048}, "action": {"max_model_recoveries": 0}}


def names(index):
    return "fiction.read_gate_incident" if index == 1 else "fiction.read_scene"


class StagingModel:
    def __init__(self):
        self.step = 0

    async def call_llm(self, *_args, **_kwargs):
        self.step += 1
        call = {"role": "assistant", "content": "Fixture staging complete."}
        if self.step <= STEPS:
            call = {"role": "assistant", "reasoning_content": "Deterministic fixture operation.",
                    "tool_calls": [{"id": f"stage_{self.step}", "type": "function",
                    "function": {"name": "tool_call", "arguments": json.dumps({"tool_name": names(self.step), "args": {"scene": self.step}})}}]}
        return {"status": "success", **response_fields(call), "usage": {"prompt_tokens": 0, "completion_tokens": 0}}


def compile_context(messages, observations):
    return ContextCompiler.project_observations(messages, observations, per_result_chars=8000, total_chars=32000)


async def stage(emitter, phrase):
    async def prepare(messages, observations):
        return compile_context(messages, observations)

    def produce(_, args):
        scene = args["scene"]
        if scene == 1:
            return {"title": "Initial gate incident", "record": f"The clerk Nera Vale entered the phrase {phrase} and opened the inner gate."}
        return {"title": f"Scene {scene}: cataloguing recovered lanterns",
                "record": f"Archivist Ivo tracked {scene * 3} lanterns, noted scratches in the cabinet and signed the inventory ledger."}

    checkpoints = []
    service = ActionService(conversation_core=StagingModel(), event_emitter=emitter)
    await service.run_action(goal=GOAL, messages=[{"role": "system", "content": build_action_protocol_prompt()},
        {"role": "user", "content": GOAL}], user_id=OWNER, session_id=SESSION, budget=STEPS + 2,
        user_config=POLICY, tool_executor=produce, prepare_messages=prepare, checkpoint_sink=checkpoints.append)
    checkpoint = next(row for row in checkpoints if row["step"] == STEPS and not row["pending_calls"] and not row["result"])
    evidence = checkpoint["observations"][0]["observation_id"]
    checkpoint["messages"].append({"role": "user", "content": QUESTION})
    checkpoint["budget"] = STEPS + 5
    return checkpoint, evidence


class EvaluationConversation(PrometheaConversation):
    def __init__(self, client, model):
        self.eval_client, self.eval_model = client, model

    def _get_client_params(self, *_args, **_kwargs):
        return "fixture-local", str(self.eval_client.base_url), self.eval_model, 0, 2048, []

    def _resolve_model_candidates(self, *_args, **_kwargs):
        return [self.eval_model]

    def _resolve_async_client(self, *_args, **_kwargs):
        return self.eval_client


async def run(output, proxy=None, endpoint=None):
    phrase = "ember-sluice-" + secrets.token_hex(4)
    emitter = EventEmitter(event_log=RuntimeEventLog(storage_path=str(output / "events.jsonl")))
    with patch("gateway.user_secrets.resolve_llm_runtime_settings", return_value={"tool_protocol": "native"}):
        checkpoint, evidence = await stage(emitter, phrase)
    server = SimpleNamespace(event_emitter=emitter)
    tools = {tool.name: tool for tool in (RuntimeListObservationsTool(gateway_server=server), RuntimeReadObservationTool(gateway_server=server))}
    ctx = ToolInvocationContext(user_id=OWNER, session_id=SESSION)
    calls = []

    async def execute(name, args):
        if name not in tools:
            raise PermissionError("Only the two read-only Runtime evidence tools are available in this trial.")
        result = await tools[name].invoke(args, ctx)
        calls.append({"name": name, "args": args, "result": result})
        return result

    async def prepare(messages, observations):
        visible = compile_context(messages, observations)
        visible[0] = {**visible[0], "content": build_action_protocol_prompt() + "\nAvailable read-only tools:\n" + json.dumps({
            name: {"description": tool.description, "schema": tool.input_schema} for name, tool in tools.items()})}
        return visible

    first = await prepare(checkpoint["messages"], checkpoint["observations"])
    wire = request_fields(first, {"protocol": "native", "purpose": "action", "wire_history": checkpoint["model_wire"],
                                  "observations": checkpoint["observations"]})
    initial = json.dumps(wire, ensure_ascii=False)
    assert any(row.get("name") == CONTEXT_ANCHOR for row in first)
    assert phrase not in initial and "Nera Vale" not in initial and evidence not in initial
    report = {"staged_steps": STEPS, "answer_and_id_absent": True, "expected_phrase": phrase,
              "expected_evidence": evidence, "initial_request_bytes": len(initial.encode()), "provider_calls": 0}
    if proxy is None:
        return report
    async with AsyncOpenAI(base_url=endpoint, api_key="fixture-local", max_retries=0, timeout=75) as client:
        with patch("conversation_core.resolve_multimodal_runtime_settings", return_value={}), patch("conversation_core._model_quote", return_value=None):
            result = await ActionService(conversation_core=EvaluationConversation(client, proxy.model), event_emitter=emitter).run_action(
                goal=GOAL, messages=[], user_id=OWNER, session_id=SESSION, user_config=POLICY,
                checkpoint=checkpoint, tool_executor=execute, prepare_messages=prepare,
            )
    answer = result.get("content", "")
    listed = any(call["name"] == "runtime.list_observations" and any(row["observation_id"] == evidence for row in call["result"]["observations"]) for call in calls)
    read = any(call["name"] == "runtime.read_observation" and call["args"].get("observation_id") == evidence and phrase in call["result"]["content"] for call in calls)
    cited = evidence in result.get("evidence_refs", []) or evidence in answer
    exact = phrase in answer and "Nera Vale" in answer
    report.update(result_status=result.get("status"), answer=answer, listed=listed, read=read, cited=cited,
                  exact=exact, passed=listed and read and cited and exact, tool_calls=calls,
                  execution_outcome=result.get("execution_outcome"))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorized-usd", type=float, default=0)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / ".tmp").resolve()) or not 0 <= args.authorized_usd <= .05:
        parser.error("use a fresh .tmp directory and a budget between zero and $0.05")
    output.mkdir(parents=True)
    if args.authorized_usd:
        values, _, rates = eval_settings(ROOT / ".env.eval")
        proxy = MeteredProxy(values, rates, output, ceiling=args.authorized_usd)
        proxy.budget.max_calls = 6
        with proxy.serve() as endpoint:
            report = asyncio.run(run(output, proxy, endpoint))
        report.update(provider_calls=proxy.budget.calls, conservative_cost_usd=proxy.budget.cost_usd,
                      usage_known=proxy.budget.usage_known, stop_reason=proxy.stop_reason, receipts=proxy.receipts)
    else:
        report = asyncio.run(run(output))
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"receipts", "tool_calls"}}, indent=2))


if __name__ == "__main__":
    main()
