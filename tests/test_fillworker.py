import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_fillworker_js():
    script = Path(__file__).resolve().parent.parent / "tools" / "test" / "run_worker_test.js"
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "fillworker ok" in out.stdout
    assert "fillworker local ok" in out.stdout
