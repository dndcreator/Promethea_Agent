"""JUnit facts shared by the test runner and baseline comparison."""
from collections import Counter, defaultdict
import xml.etree.ElementTree as ET


def read_junit(path):
    modules = defaultdict(Counter)
    failures = []
    for case in ET.parse(path).getroot().iter("testcase"):
        owner = case.get("classname", "unknown")
        skipped = case.find("skipped")
        status = "failed" if case.find("failure") is not None or case.find("error") is not None else "xfailed" if skipped is not None and skipped.get("type") == "pytest.xfail" else "skipped" if skipped is not None else "passed"
        modules[owner][status] += 1
        modules[owner]["seconds"] += float(case.get("time", 0))
        if status == "failed":
            detail = case.find("failure")
            if detail is None:
                detail = case.find("error")
            failures.append({"case": owner + "::" + case.get("name", ""), "type": detail.get("type", "assertion"), "message": detail.get("message", "")[:1000]})
    totals = Counter()
    for counts in modules.values():
        totals.update(counts)
    return {"totals": dict(totals), "modules": dict(modules), "failures": failures}


def compare_runs(before, after):
    result = {}
    for owner in sorted(before["modules"].keys() | after["modules"].keys()):
        old, new = before["modules"].get(owner, {}), after["modules"].get(owner, {})
        result[owner] = {"before": old, "after": new, "new_failures": max(0, new.get("failed", 0) - old.get("failed", 0))}
    return result
