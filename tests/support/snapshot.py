"""Copy distributable source only; never operator configuration or runtime data."""
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def copy_code(destination):
    for folder in ("gateway", "core", "computer", "agentkit", "memory", "skills", "channels", "prompts", "utils", "tests/support"):
        source = ROOT / folder
        if not source.exists():
            continue
        for path in source.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix not in {".py", ".js", ".yaml", ".toml", ".md"} and path.name != "agent-manifest.json":
                continue
            target = destination / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    for path in ROOT.glob("*.py"):
        shutil.copyfile(path, destination / path.name)
    (destination / "tests").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "tests/__init__.py", destination / "tests/__init__.py")


def copy_production_code(destination):
    """Include tracked production plugins/assets, never deployment config or data."""
    copy_code(destination)
    paths = subprocess.check_output(['git', 'ls-files', '--', 'utils', 'brain', 'extensions', 'UI/index.html'], cwd=ROOT, text=True).splitlines()
    for name in paths:
        source = ROOT / name
        if source.is_file() and source.suffix in {'.py', '.json', '.js', '.yaml', '.toml', '.md', '.html'}:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
