import os
from pathlib import Path
import subprocess
import sys
import tempfile


def test_pytest_and_child_process_share_checkout_local_storage(
    project_root_path, tmp_path, tmp_path_factory, pytestconfig
):
    run = Path(os.environ["PROMETHEA_TEST_TMP_ROOT"]).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    assert run.is_relative_to(project_root_path)
    assert tmp_path.resolve().is_relative_to(run)
    assert temp.is_relative_to(run)
    pytest_temp = tmp_path_factory.getbasetemp().resolve()
    if pytestconfig.option.basetemp:
        assert pytest_temp == Path(pytestconfig.option.basetemp).resolve()
    else:
        assert pytest_temp.is_relative_to(run)
    child_temp = subprocess.check_output(
        [sys.executable, "-c", "import tempfile; print(tempfile.gettempdir())"],
        text=True,
        timeout=10,
    )
    assert Path(child_temp.strip()).resolve() == temp
