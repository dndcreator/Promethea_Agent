from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _iter_python_files(*roots: str):
    for root in roots:
        base = PROJECT_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def test_no_datetime_utcnow_in_runtime_code():
    hits = []
    for path in _iter_python_files("gateway", "memory"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "datetime.utcnow(" in text:
            hits.append(str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"))
    assert not hits, f"Found deprecated datetime.utcnow usage: {hits}"


def test_no_naive_datetime_default_factory_in_runtime_models():
    hits = []
    for path in _iter_python_files("gateway", "memory"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "Field(default_factory=datetime.now)" in text:
            hits.append(str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"))
    assert not hits, f"Found naive datetime default factory usage: {hits}"

