"""Evaluation-only artifact milestones; model prose never counts as progress."""
from copy import deepcopy
import json
import math
import os
import time

from tests.support.evaluation import digest


def json_result_matches(actual, expected):
    try:
        return digest(json.loads(actual)) == digest(expected)
    except (ValueError, TypeError):
        return False


def decision_summary(content, usage, finish):
    """Report provider accounting and syntax, never infer hidden reasoning quality."""
    from gateway.action.model_action import InvalidModelAction, parse_model_action
    usage = usage or {}
    details = usage.get("completion_tokens_details") or {}
    reasoning = details.get("reasoning_tokens")
    completion = usage.get("completion_tokens")
    known = type(reasoning) is int and type(completion) is int and 0 <= reasoning <= completion
    try:
        action = parse_model_action(content)
        proposal = {"kind": action.kind, "tools": [{"id": call.call_id, "name": call.tool_name,
                     "argument_chars": len(json.dumps(call.arguments, ensure_ascii=False))} for call in action.calls]}
        complete_action = True
    except InvalidModelAction as exc:
        proposal, complete_action = {"invalid_reason": exc.reason}, False
    region = None
    if finish == "length":
        region = "before_action_text" if not content.strip() else "complete_action_not_accepted" if complete_action else "incomplete_action_text"
    return {"proposal": proposal, "reasoning_tokens": reasoning if known else None,
            "non_reasoning_completion_tokens": completion - reasoning if known else None,
            "truncation_region": region, "output_tail": content[-240:] if finish == "length" else None}


def decision_trace(receipts, model_calls, observations, progress):
    steps = {row["model_step_id"]: index for index, row in enumerate(model_calls, 1)}
    snapshots = (progress or {}).get("snapshots") or []
    rows = []
    for index, receipt in enumerate(receipts, 1):
        facts = [row for row in observations if steps.get(row.get("model_step_id")) == index]
        snapshot = next((row for row in reversed(snapshots) if row["call"] <= index), None)
        next_receipt = receipts[index] if index < len(receipts) else None
        rows.append({"call": index, "request_id": receipt.get("request_id"), "purpose": receipt.get("purpose"),
                     "max_tokens": receipt.get("max_tokens"), "usage": receipt.get("usage"), **receipt.get("decision", {}),
                     "output_budget": receipt.get("output_budget"),
                     "observations": [{"id": row.get("observation_id"), "tool": row.get("tool_name"), "ok": row.get("ok"),
                                       "error": (row.get("error") or {}).get("code")} for row in facts],
                     "successful_file_commits": sum(row.get("ok") and row.get("tool_name") == "workspace.write_file" for row in facts),
                     "passed_checks": snapshot["passed_checks"] if snapshot else [],
                     "artifact_hash": snapshot["artifact_hash"] if snapshot else None,
                     "next_allowance": next_receipt.get("max_tokens") if next_receipt else None,
                     "recovery_followed": bool(next_receipt and next_receipt.get("purpose") == "action" and any((row.get("error") or {}).get("code") in {"MODEL_OUTPUT_LIMIT", "MODEL_EMPTY_RESPONSE", "INVALID_MODEL_ACTION"} for row in facts))})
    return rows


def predict_output_budget(contract, settings):
    """Experimental structural prior, never a semantic classifier or grader."""
    if contract is None:
        return {"initial": settings["fallback_tokens"], "source": "conservative_fallback", "signals": {}}
    signals = {}
    for name in settings["weights"]:
        values = contract.get(name)
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values) or len(set(values)) != len(values):
            raise ValueError("delivery contract requires unique named fields, actions and collections")
        signals[name] = len(values)
    units = sum(signals[name] * weight for name, weight in settings["weights"].items())
    for tier in settings["tiers"]:
        if tier["max_units"] is None or units <= tier["max_units"]:
            return {"initial": tier["tokens"], "source": "declared_delivery_contract", "signals": signals, "units": units}
    raise ValueError("prediction tiers must include an unbounded final tier")


def resolve_output_policy(policy, case, prediction):
    resolved = dict(policy)
    if policy.get("predict"):
        result = predict_output_budget(case.get("delivery_contract"), prediction)
        resolved.update(initial=result["initial"], prediction=result)
        if not policy.get("adaptive"):
            resolved["ceiling"] = result["initial"]
    if not 0 < resolved["initial"] <= resolved["ceiling"]:
        raise ValueError("invalid experimental output allowance")
    return resolved


async def browser_checks(html, checks):
    from playwright.async_api import async_playwright, Error as BrowserError

    outcomes = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ.get("CANVAS_TEST_BROWSER_CHANNEL", "msedge"), headless=True, chromium_sandbox=True)
        try:
            for check in checks:
                context = await browser.new_context(accept_downloads=False, service_workers="block")
                errors = []
                try:
                    async def route(request):
                        if request.request.url == "https://evaluation.invalid/" and request.request.resource_type == "document":
                            await request.fulfill(body=html, content_type="text/html", headers={
                                "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"})
                        else:
                            await request.abort()
                    await context.route("**/*", route)
                    page = await context.new_page()
                    page.set_default_timeout(1000)
                    page.on("pageerror", lambda error: errors.append(str(error)[:300]))
                    await page.goto("https://evaluation.invalid/", wait_until="load", timeout=4000)
                    for action in check.get("actions", []):
                        if "fill" in action:
                            for selector, value in action["fill"].items():
                                await page.locator(selector).fill(str(value))
                        elif "click" in action:
                            await page.locator(action["click"]).click()
                        elif "check" in action:
                            await page.locator(action["check"]).check()
                        elif action.get("reload"):
                            await page.reload(wait_until="load", timeout=4000)
                        else:
                            raise ValueError("unsupported evaluation action")
                    mismatches = []
                    for assertion in check["assertions"]:
                        locator = page.locator(assertion["selector"])
                        if "count" in assertion:
                            actual = await locator.count()
                            passed = actual == assertion["count"]
                        elif "checked" in assertion:
                            actual = await locator.is_checked()
                            passed = actual == assertion["checked"]
                        else:
                            actual = await locator.evaluate("node => String(node.value ?? node.textContent).trim().slice(0, 500)")
                            if "json" in assertion:
                                passed = json_result_matches(actual, assertion["json"])
                            elif "number" in assertion:
                                try:
                                    passed = math.isfinite(float(actual)) and math.isclose(float(actual), assertion["number"], rel_tol=0, abs_tol=0.000001)
                                except ValueError:
                                    passed = False
                            else:
                                passed = actual == assertion["text"]
                        if not passed:
                            mismatches.append({"selector": assertion["selector"], "expected": {key: value for key, value in assertion.items() if key != "selector"}, "actual": actual})
                    outcomes[check["id"]] = {"passed": not mismatches and not errors, "mismatches": mismatches, "script_errors": errors}
                except BrowserError as exc:
                    outcomes[check["id"]] = {"passed": False, "error_type": type(exc).__name__, "script_errors": errors}
                finally:
                    await context.close()
        finally:
            await browser.close()
    return outcomes


def progress_summary(snapshots, calls):
    initial = set(snapshots[0]["passed_checks"])
    previous = initial
    seen = set(initial)
    advances, regressions = [], []
    for snapshot in snapshots[1:]:
        current = set(snapshot["passed_checks"])
        gained, lost = current - previous, previous - current
        if gained:
            advances.append({"call": snapshot["call"], "checks": sorted(gained)})
        if lost:
            regressions.append({"call": snapshot["call"], "checks": sorted(lost)})
        seen |= current
        previous = current
    final = snapshots[-1]
    delivery = next((row["call"] for row in snapshots if row["all_passed"]), None)
    return {"initial_passed": sorted(initial), "final_passed": final["passed_checks"],
            "failed_checks": final["failed_checks"], "goal_met": final["all_passed"],
            "new_checks_ever_passed": sorted(seen - initial), "advances": advances, "regressions": regressions,
            "first_delivery_call": delivery,
            "calls_after_last_check_gain": calls - (advances[-1]["call"] if advances else 0),
            "limits": "Check gains are not semantic thinking quality. Tail calls include necessary final reporting; repeated reads can be legitimate verification."}


class ProgressRecorder:
    def __init__(self, case, workspace, output, endpoint):
        self.case, self.workspace, self.output, self.endpoint = case, workspace, output, endpoint
        self.start_call = len(endpoint.receipts)
        self.snapshots, self.errors, self.observations = [], [], []
        self.seen_results, self.duplicate_results = set(), 0
        self.last_hash, self.last_checks = None, None
        self.grader_seconds = 0.0

    async def capture(self, reason, observation_id=None):
        path = (self.workspace / self.case["artifact"]).resolve()
        if not path.is_relative_to(self.workspace.resolve()):
            raise ValueError("evaluation artifact escapes workspace")
        content = path.read_text(encoding="utf-8") if path.is_file() else None
        signature = digest(content)
        if self.last_checks is None or signature != self.last_hash:
            if content is None:
                checks = {row["id"]: {"passed": False, "error_type": "MissingArtifact"} for row in self.case["checks"]}
            else:
                started = time.monotonic()
                checks = await browser_checks(content, self.case["checks"])
                self.grader_seconds += time.monotonic() - started
                self.output.mkdir(parents=True, exist_ok=True)
                (self.output / f"{len(self.snapshots):03d}-{signature[:12]}.html").write_text(content, encoding="utf-8")
            self.last_hash, self.last_checks = signature, checks
        else:
            checks = self.last_checks
        self.snapshots.append({"reason": reason, "observation_id": observation_id, "call": len(self.endpoint.receipts) - self.start_call,
                               "artifact_hash": signature, "artifact_chars": len(content) if content else 0,
                               "passed_checks": [key for key, row in checks.items() if row["passed"]],
                               "failed_checks": [key for key, row in checks.items() if not row["passed"]],
                               "all_passed": bool(checks) and all(row["passed"] for row in checks.values()), "checks": deepcopy(checks)})

    async def observe(self, event):
        payload = event.payload
        result = {"tool": payload.get("tool_name"), "result": payload.get("structured_result"), "error": payload.get("error")}
        signature = digest(result)
        self.duplicate_results += int(signature in self.seen_results)
        self.seen_results.add(signature)
        self.observations.append({"id": payload.get("observation_id"), "call": len(self.endpoint.receipts) - self.start_call,
                                  "tool": payload.get("tool_name"), "ok": payload.get("ok"), "result_hash": signature})
        try:
            await self.capture("observation", payload.get("observation_id"))
        except Exception as exc:
            self.errors.append({"type": type(exc).__name__, "observation_id": payload.get("observation_id")})

    def report(self):
        return {**progress_summary(self.snapshots, len(self.endpoint.receipts) - self.start_call),
                "changed_artifact_versions": len({row["artifact_hash"] for row in self.snapshots[1:]
                                                   if row["artifact_chars"] and row["artifact_hash"] != self.snapshots[0]["artifact_hash"]}),
                "final_artifact_chars": self.snapshots[-1]["artifact_chars"],
                "snapshots": self.snapshots, "observations": self.observations,
                "duplicate_observation_results": self.duplicate_results, "evaluation_errors": self.errors,
                "grader_seconds": self.grader_seconds}


def summarize_policies(rows, policies):
    from gateway.model_usage import cached_tokens

    ids = {policy["id"] for policy in policies}
    groups = {(row["trial"], row["id"]) for row in rows}
    complete = {group for group in groups if {row["condition"] for row in rows if (row["trial"], row["id"]) == group and row["evaluation_complete"]} == ids}
    summary = {}
    for policy in policies:
        matched = [row for row in rows if row["condition"] == policy["id"] and (row["trial"], row["id"]) in complete]
        goals = sum(row["progress"]["goal_met"] for row in matched)
        cost = sum(row["conservative_cost_usd"] for row in matched)
        receipts = [receipt for row in matched for receipt in row.get("receipts", [])]
        reasoning = [receipt.get("reasoning_chars") for receipt in receipts]
        usages = [receipt["usage"] for receipt in receipts if receipt.get("usage")]
        cache = [cached_tokens(usage) for usage in usages]
        summary[policy["id"]] = {"comparable_trials": len(matched), "functional_goals_met": goals,
            "full_deliveries": sum(row["delivered"] for row in matched), "calls": sum(row["calls"] for row in matched),
            "conservative_cost_usd": cost, "cost_per_functional_goal_usd": cost / goals if goals else None,
            "completion_tokens": sum(receipt["usage"]["completion_tokens"] for receipt in receipts if receipt.get("usage")),
            "prompt_tokens": sum(usage.get("prompt_tokens", 0) for usage in usages),
            "cache_hit_tokens": sum(cache) if cache and all(value is not None for value in cache) else None,
            "calls_with_functional_gains": sum(len({gain["call"] for gain in row["progress"]["advances"]}) for row in matched),
            "duplicate_observation_results": sum(row["progress"].get("duplicate_observation_results", 0) for row in matched),
            "canonical_answer_proposal_chars": sum(receipt.get("proposed_answer_chars") or 0 for receipt in receipts),
            "provider_reasoning_chars": sum(reasoning) if reasoning and all(value is not None for value in reasoning) else None,
            "protocol_errors": sum(sum(code == "INVALID_MODEL_ACTION" for code in row["observation_errors"]) for row in matched),
            "output_truncations": sum(sum(code == "MODEL_OUTPUT_LIMIT" for code in row["observation_errors"]) for row in matched),
            "recovery_retries": sum(row.get("recovery_retries", 0) for row in matched),
            "allowance_growths": sum(sum(current["max_tokens"] > previous["max_tokens"] for previous, current in zip(row.get("receipts", []), row.get("receipts", [])[1:])) for row in matched),
            "by_task": [{"id": row["id"], "trial": row["trial"], "goal_met": row["progress"]["goal_met"],
                         "calls": row["calls"], "initial_passed": row["progress"]["initial_passed"],
                         "final_passed": row["progress"]["final_passed"], "failed_checks": row["progress"]["failed_checks"],
                         "first_delivery_call": row["progress"]["first_delivery_call"],
                         "changed_artifact_versions": row["progress"].get("changed_artifact_versions"),
                         "final_artifact_chars": row["progress"].get("final_artifact_chars"),
                         "regressions": row["progress"]["regressions"]} for row in matched]}
    return {"comparable_groups": sorted(complete), "policies": summary}


def summarize_categories(rows, policies):
    return {category: summarize_policies([row for row in rows if row.get("category") == category], policies)
            for category in sorted({row["category"] for row in rows if row.get("category")})}
