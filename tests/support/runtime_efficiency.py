"""Cost-bounded paired policy experiments over isolated, real Runtime services."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4

from dotenv import dotenv_values

from gateway.action import ActionService
from gateway.protocol import RequestType
from tests.support.evaluation import Budget, BudgetExceeded, digest, hard_checks


def paired_summary(report):
    paired = {tuple(value) for value in report["fully_paired_cases"]}
    summary = {}
    rates = report["input_output_usd_per_million"]
    from gateway.model_usage import cached_tokens
    for condition in ("fixed", "adaptive"):
        rows = [row for row in report["cases"] if row["condition"] == condition and (row["trial"], row["id"]) in paired]
        receipts = [receipt for row in rows for receipt in row["receipts"]]
        usages = [receipt["usage"] for receipt in receipts if receipt.get("usage")]
        prompt = sum(usage.get("prompt_tokens", 0) for usage in usages)
        completion = sum(usage.get("completion_tokens", 0) for usage in usages)
        known = len(usages) == len(receipts)
        cache = [cached_tokens(usage) for usage in usages]
        delivered = sum(row["delivered"] for row in rows)
        cost = (prompt * rates[0] + completion * rates[1]) / 1_000_000 if known else None
        summary[condition] = {"paired_cases": len(rows), "delivered": delivered, "calls": len(receipts),
                              "prompt_tokens": prompt if known else None, "completion_tokens": completion if known else None,
                              "cache_hit_tokens": sum(cache) if known and all(value is not None for value in cache) else None,
                              "invalid_outputs": sum(sum(code in {"MODEL_OUTPUT_LIMIT", "MODEL_EMPTY_RESPONSE", "INVALID_MODEL_ACTION"} for code in row["observation_errors"]) for row in rows),
                              "conservative_cost_usd": cost,
                              "cost_per_delivered_usd": cost / delivered if cost is not None and delivered else None}
    return summary


def eval_settings(path):
    values = {key: str(value) for key, value in dotenv_values(path).items() if value is not None}
    if any(not key.startswith("PROMETHEA_EVAL_") for key in values):
        raise ValueError("evaluation file must contain evaluation-only settings")
    required = ["BASE_URL", "API_KEY", "MODEL", "INPUT_USD_PER_MILLION", "OUTPUT_USD_PER_MILLION"]
    if any(not values.get("PROMETHEA_EVAL_AGENT_" + key) for key in required):
        raise ValueError("evaluation endpoint, model and price ceilings must be explicitly configured")
    ceiling = float(values.get("PROMETHEA_EVAL_MAX_COST_USD") or 0)
    rates = tuple(float(values["PROMETHEA_EVAL_AGENT_" + key + "_USD_PER_MILLION"]) for key in ("INPUT", "OUTPUT"))
    if not math.isfinite(ceiling) or ceiling <= 0 or any(not math.isfinite(rate) or rate < 0 for rate in rates):
        raise ValueError("finite positive total cost and nonnegative price ceilings required")
    return values, ceiling, rates


class PairedEndpoint:
    def __init__(self, values, budget, rates, *, request_timeout=30, journal_path=None, max_request_cost_usd=None):
        from openai import AsyncOpenAI
        self.model = values["PROMETHEA_EVAL_AGENT_MODEL"]
        self.identity = {"model": self.model, "endpoint_hash": digest(values["PROMETHEA_EVAL_AGENT_BASE_URL"])}
        self.client = AsyncOpenAI(base_url=values["PROMETHEA_EVAL_AGENT_BASE_URL"], api_key=values["PROMETHEA_EVAL_AGENT_API_KEY"], max_retries=0, timeout=request_timeout)
        self.budget, self.rates, self.receipts = budget, rates, []
        self.stop_reason = None
        self.journal_path, self.max_request_cost_usd = journal_path, max_request_cost_usd

    def _journal(self, record):
        if self.journal_path is not None:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.journal_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def _request_parameters(self, messages, maximum, user_config):
        return {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": maximum}

    def _decode_message(self, message, user_config):
        return message.content or "", {}

    async def call_llm(self, messages, user_config=None, **_kwargs):
        maximum = int((user_config or {}).get("api", {}).get("max_tokens") or 2000)
        parameters = self._request_parameters(messages, maximum, user_config)
        try:
            reserved = self.budget.reservation(parameters, maximum, self.rates)
            if self.max_request_cost_usd is not None and reserved["reserved_cost_usd"] > self.max_request_cost_usd:
                raise BudgetExceeded("single-request currency reserve exceeded")
            self.budget.admit(parameters, maximum, self.rates)
        except BudgetExceeded as exc:
            self.stop_reason = str(exc)
            raise
        local_id = f"eval_{uuid4().hex}"
        try:
            self._journal({"state": "pending", "local_id": local_id, "at": datetime.now(timezone.utc).isoformat(),
                           "request_hash": digest(parameters), "request": parameters, "max_tokens": maximum, **reserved})
        except Exception:
            self.stop_reason = "request journal unavailable; no transport send"
            raise
        started = time.monotonic()
        try:
            result = await self.client.chat.completions.create(**parameters)
        except Exception as exc:
            self.budget.usage_known = False  # Unknown billing stops the entire experiment.
            self.receipts.append({"error_type": type(exc).__name__, "usage": None, "max_tokens": maximum,
                                  "local_id": local_id, **reserved,
                                  "input_chars": len(json.dumps(parameters, ensure_ascii=False)),
                                  "recorded_at": datetime.now(timezone.utc).isoformat()})
            self._journal({"state": "unresolved", "local_id": local_id, "receipt": self.receipts[-1]})
            raise RuntimeError("Evaluation provider request failed: " + type(exc).__name__) from None
        usage = result.usage.model_dump() if result.usage else None
        self.budget.settle(usage, self.rates)
        choice = result.choices[0] if result.choices else None
        finish = choice.finish_reason if choice else None
        adapter_error = None
        try:
            content, protocol = self._decode_message(choice.message, user_config) if choice else ("", {})
        except Exception as exc:
            self.stop_reason = "evaluation adapter failed: " + type(exc).__name__
            content, protocol, adapter_error = "", {}, exc
        reasoning = getattr(choice.message, "reasoning_content", None) if choice else None
        try:
            proposal = json.loads(content)
        except ValueError:
            proposal = None
        code = "MODEL_OUTPUT_LIMIT" if finish == "length" else "MODEL_EMPTY_RESPONSE" if not content.strip() else None
        from tests.support.task_progress import decision_summary
        self.receipts.append({"local_id": local_id, "request_id": result.id, "served_model": result.model, "recorded_at": datetime.now(timezone.utc).isoformat(), "usage": usage, "max_tokens": maximum, "input_chars": len(json.dumps(parameters, ensure_ascii=False)), "seconds": time.monotonic() - started, **reserved, **protocol,
                              "code": code, "response_hash": digest(content), "purpose": (user_config or {}).get("_runtime_call", {}).get("purpose"),
                              "response_chars": len(content), "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else None,
                              "decision": decision_summary(content, usage, finish),
                              **({"output_budget": deepcopy(user_config["_eval_output_budget"])} if (user_config or {}).get("_eval_output_budget") else {}),
                              "proposed_answer_chars": len(str(proposal.get("content") or "")) if isinstance(proposal, dict) and proposal.get("action") == "answer" else None})
        try:
            self._journal({"state": "settled" if self.budget.usage_known else "unresolved", "local_id": local_id, "receipt": self.receipts[-1]})
        except Exception:
            self.stop_reason = "receipt journal unavailable"
            raise
        if adapter_error is not None:
            raise adapter_error
        return {"status": "error" if code else "success", "code": code, "content": content, "usage": usage, "finish_reason": finish, "request_id": result.id, "model_used": self.model, "max_tokens": maximum, **protocol}


class FixedOutputBaseline(ActionService):
    """Test-only prior retry policy; no production compatibility path is retained."""
    def _recover_output(self, action_run, code, signature):
        return True, "No action executed. Return one complete JSON action; split large work."


def calculator_result_matches(value, a, b, expected):
    """Accept a numeric result or an explicit input-addition equation, never code."""
    import ast
    from decimal import Decimal, InvalidOperation

    text = str(value).strip()
    if len(text) > 160:
        return False
    target = Decimal(str(expected))
    try:
        result = Decimal(text)
        return result.is_finite() and result == target
    except InvalidOperation:
        pass
    left, separator, right = text.partition("=")
    if not separator:
        return False
    try:
        expression = ast.parse(left.strip(), mode="eval").body
        if not isinstance(expression, ast.BinOp) or not isinstance(expression.op, ast.Add):
            return False
        def number(node):
            sign = 1
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
                sign = -1 if isinstance(node.op, ast.USub) else 1
                node = node.operand
            if not isinstance(node, ast.Constant) or type(node.value) not in (int, float):
                raise ValueError("not a numeric operand")
            return sign * Decimal(str(node.value))
        result = Decimal(right.strip())
        return (result.is_finite() and result == target and number(expression.left) == Decimal(str(a))
                and number(expression.right) == Decimal(str(b)))
    except (SyntaxError, ValueError, InvalidOperation):
        return False


async def calculator_check(html):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ.get("CANVAS_TEST_BROWSER_CHANNEL", "msedge"), headless=True, chromium_sandbox=True)
        try:
            context = await browser.new_context(accept_downloads=False, service_workers="block")
            await context.route("**/*", lambda route: route.abort())
            page = await context.new_page()
            page.set_default_timeout(4000)
            await page.set_content(html, wait_until="domcontentloaded", timeout=4000)
            for a, b, expected in [(2, 3, 5), (-2.5, 1, -1.5)]:
                await page.locator("#a").fill(str(a))
                await page.locator("#b").fill(str(b))
                await page.locator("#calculate").click()
                value = await page.locator("#result").evaluate("node => node.value ?? node.textContent")
                if not calculator_result_matches(value, a, b, expected):
                    return False
            return True
        finally:
            await browser.close()


async def live_case(case, endpoint, root, condition, *, policy=None, action_service_factory=None):
    from tests.support.runtime import runtime_at
    from agentkit.tools.standard.runtime_tools import RuntimeReadObservationTool
    from gateway.protocol import EventType
    host = runtime_at(root, endpoint)
    start_receipt = len(endpoint.receipts)
    host.capability_service.register_tool(RuntimeReadObservationTool(gateway_server=host))
    initial = host.config_service.get_merged_config
    def settings(user):
        cfg = initial(user)
        cfg["api"]["max_tokens"] = 2000
        cfg["api"].update(api_key="", base_url="https://example.invalid/v1", model=endpoint.model)
        cfg["api"]["output_token_limit"] = 2000 if condition == "fixed" else 4096
        if condition == "fixed":
            cfg["action"].update(observation_chars=16000, observation_history_chars=96000)
        if policy is not None:
            cfg["api"].update(max_tokens=policy["initial"], output_token_limit=policy["ceiling"])
            cfg["action"].update(max_steps=policy["max_steps"], progress_grace_steps=0,
                                 observation_chars=8000, observation_history_chars=32000)
        return cfg
    host.config_service.get_merged_config = settings
    if action_service_factory is not None:
        host.conversation_service.action_service = action_service_factory(host.conversation_service.action_service)
    if condition == "fixed":
        host.conversation_service.action_service = FixedOutputBaseline(conversation_core=endpoint, event_emitter=host.event_emitter, task_service=host.task_service, capability_service=host.capability_service)
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="evaluation")
    files = dict(case.get("files") or {})
    if case.get("long_source"):
        files["source.txt"] = "Background reference.\n" * 3000 + "\nRELEASE_CODE=TAIL-ORCHID-29\n"
    for name, content in files.items():
        host.workspace_service.create_document(handle=handle, relative_path=name, content=content, requester_user_id="alice")
    progress = None
    if case.get("checks"):
        from tests.support.task_progress import ProgressRecorder
        progress = ProgressRecorder(case, Path(handle.root_path), root / "artifact-versions", endpoint)
        host.event_emitter.on(EventType.ACTION_OBSERVATION_COMMITTED, progress.observe)
        await progress.capture("initial")
    message = case["turns"][0]
    if case.get("delivery_contract") is not None:
        message += "\nStructured delivery requirements:\n" + json.dumps(case["delivery_contract"], ensure_ascii=False, sort_keys=True)
    response = await host.handle_http_request(method=RequestType.CHAT, params={"message": message, "session_id": "evaluation"}, user_id="alice")
    expected = case["expect"]
    names = set(expected.get("artifacts", {})) | set(expected.get("artifact_json", {}))
    if expected.get("calculator"):
        names.add(expected["calculator"])
    if case.get("artifact"):
        names.add(case["artifact"])
    artifacts = {name: (Path(handle.root_path) / name).read_text(encoding="utf-8") if (Path(handle.root_path) / name).is_file() else None for name in names}
    observations = [row.payload for row in host.event_emitter.get_history(EventType.ACTION_OBSERVATION_COMMITTED)]
    evidence = {"status": response.payload.get("status") if response.ok else "error", "answer": (response.payload or {}).get("response", ""), "tools": [row["tool_name"] for row in observations], "artifacts": artifacts}
    failures = hard_checks(case, evidence)
    for name, expected_json in expected.get("artifact_json", {}).items():
        try:
            if json.loads(artifacts[name]) != expected_json:
                failures.append("json_mismatch:" + name)
        except (ValueError, TypeError):
            failures.append("invalid_json:" + name)
    if expected.get("calculator"):
        try:
            if not artifacts[expected["calculator"]] or not await calculator_check(artifacts[expected["calculator"]]):
                failures.append("calculator_interaction_failed")
        except Exception as exc:
            failures.append("calculator_validation:" + type(exc).__name__)
    progress_report = None
    if progress is not None:
        await progress.capture("final")
        progress_report = progress.report()
        failures.extend("functional_check:" + key for key in progress_report["failed_checks"])
    calls = [event.payload for event in host.event_emitter.get_history(EventType.MODEL_CALL_RECORDED)]
    positions = {row["model_step_id"]: index for index, row in enumerate(calls)}
    receipts = endpoint.receipts[start_receipt:]
    retries = sum(positions.get(row.get("model_step_id"), len(receipts)) + 1 < len(receipts)
                  and receipts[positions[row["model_step_id"]] + 1].get("purpose") == "action"
                  for row in observations if (row.get("error") or {}).get("code") in {"INVALID_MODEL_ACTION", "MODEL_OUTPUT_LIMIT", "MODEL_EMPTY_RESPONSE"})
    from tests.support.task_progress import decision_trace
    decisions = decision_trace(receipts, calls, observations, progress_report)
    (root / "decision-trace.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": case["id"], "condition": condition, "delivered": not failures, "failures": failures, "recovery_retries": retries,
            "answer": evidence["answer"],
            "progress": progress_report, "decision_trace": decisions,
            "artifact_hashes": {name: digest(content) for name, content in artifacts.items()},
            "observation_errors": [row["error"]["code"] for row in observations if row.get("error")],
            "goal_status": (response.payload or {}).get("execution_outcome", {}).get("goal_status") if (response.payload or {}).get("execution_outcome") else None}


async def run_live(output, env_file, corpus, repeat=1, previous_report=None):
    values, ceiling, rates = eval_settings(env_file)
    budget = Budget(max_calls=80 if previous_report else 60, max_tokens=500000, seconds=600, max_cost_usd=ceiling)
    endpoint = PairedEndpoint(values, budget, rates, journal_path=output / "requests.jsonl")
    prior_calls = 0
    prior_cost = 0
    if previous_report:
        previous = json.loads(previous_report.read_text(encoding="utf-8"))
        if not previous["usage_known"] or previous["endpoint"] != endpoint.identity or tuple(previous["input_output_usd_per_million"]) != rates:
            await endpoint.client.close()
            raise ValueError("cannot resume unknown usage or a different endpoint/price policy")
        budget.cost_usd = prior_cost = previous["conservative_cost_usd"]
        budget.calls = prior_calls = previous["model_api_calls"]
        budget.tokens = previous.get("token_usage_total", sum(sum(receipt["usage"].get(key, 0) for key in ("prompt_tokens", "completion_tokens"))
            for row in previous["cases"] for receipt in row["receipts"] if receipt.get("usage")))
        if budget.cost_usd >= ceiling:
            await endpoint.client.close()
            raise ValueError("previous spend already exhausts this experiment's configured ceiling")
    output.mkdir(parents=True, exist_ok=True)
    rows, stopped = [], None
    try:
        for trial in range(repeat):
            for index, case in enumerate(corpus["cases"]):
                order = ["fixed", "adaptive"] if (index + trial) % 2 == 0 else ["adaptive", "fixed"]
                for condition in order:
                    if not budget.usage_known or budget.remaining() <= 0:
                        raise BudgetExceeded("provider usage unavailable or deadline reached")
                    before = len(endpoint.receipts)
                    root = output / f"trial-{trial + 1}" / case["id"] / condition
                    root.mkdir(parents=True, exist_ok=True)
                    row = await live_case(case, endpoint, root, condition)
                    row.update(trial=trial + 1, calls=len(endpoint.receipts) - before, receipts=deepcopy(endpoint.receipts[before:]),
                               evaluation_complete=not endpoint.stop_reason and budget.usage_known)
                    rows.append(row)
                    (output / "progress.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                    if not budget.usage_known:
                        raise BudgetExceeded("usage unavailable; no further paid calls allowed")
                    if endpoint.stop_reason:
                        raise BudgetExceeded(endpoint.stop_reason)
    except BudgetExceeded as exc:
        stopped = str(exc)
    finally:
        await endpoint.client.close()
    paired = [(trial, case["id"]) for trial in range(1, repeat + 1) for case in corpus["cases"]
              if len([row for row in rows if row["trial"] == trial and row["id"] == case["id"] and row["evaluation_complete"]]) == 2]
    report = {"version": 1, "mode": "live_paired_policy_ablation", "corpus_hash": digest(corpus), "endpoint": endpoint.identity,
              "price_basis": "operator_configured_conservative_no_cache", "input_output_usd_per_million": rates,
              "budget_usd": ceiling, "conservative_cost_usd": budget.cost_usd if budget.usage_known else None,
              "model_api_calls": budget.calls, "usage_known": budget.usage_known, "stop_reason": stopped,
              "current_model_api_calls": budget.calls - prior_calls, "prior_cost_usd": prior_cost,
              "token_usage_total": budget.tokens, "previous_report": str(previous_report) if previous_report else None,
              "fully_paired_cases": paired, "cases": rows,
              "limits": "Shared current Runtime, permissions and stable-prefix changes; only fixed-output/retry and observation profiles differ. Not a historical checkout or a semantic Judge score."}
    report["paired_summary"] = paired_summary(report)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
