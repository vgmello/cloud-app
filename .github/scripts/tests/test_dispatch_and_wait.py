"""Unit tests for the pure helpers in dispatch_and_wait.py. The script ships with
the composite action (it lives outside the cloudapp package), so it is loaded by
path; main() and its network calls are not exercised here."""

import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "dispatch_and_wait.py"


@pytest.fixture(scope="module")
def dw():
    spec = importlib.util.spec_from_file_location("dispatch_and_wait", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collect_target_inputs_maps_and_filters(dw):
    environ = {
        "INPUT_REPO": "acme/orders",
        "INPUT_MANIFEST": ".cloud-app.yml",
        "INPUT_STACK_NAME": "orders",
        "GH_TOKEN": "secret",
        "PATH": "/usr/bin",
    }
    assert dw.collect_target_inputs(environ) == {
        "repo": "acme/orders",
        "manifest": ".cloud-app.yml",
        "stack_name": "orders",
    }


def test_collect_target_inputs_empty_when_no_inputs(dw):
    assert dw.collect_target_inputs({"GH_TOKEN": "secret", "PATH": "/usr/bin"}) == {}


def test_build_payload_shape(dw):
    assert dw.build_payload("main", {"env": "dev"}) == {
        "ref": "main",
        "inputs": {"env": "dev"},
        "return_run_details": True,
    }


def test_pick_artifact_matches_run(dw):
    artifacts = [
        {"name": "other"},
        {"name": "deployment-outputs-42", "archive_download_url": "u"},
    ]
    assert dw.pick_artifact(artifacts, 42)["archive_download_url"] == "u"


def test_pick_artifact_none_when_absent(dw):
    assert dw.pick_artifact([{"name": "deployment-outputs-99"}], 42) is None


def test_pick_artifact_none_on_empty_list(dw):
    assert dw.pick_artifact([], 42) is None


def test_extract_results_reads_json_from_zip(dw):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("deployment-results.json", json.dumps({"status": "success", "deployment_url": "https://x"}))
    assert dw.extract_results(buf.getvalue()) == {"status": "success", "deployment_url": "https://x"}


def test_extract_results_raises_when_member_missing(dw):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("other.json", "{}")
    with pytest.raises(KeyError):
        dw.extract_results(buf.getvalue())


def test_format_output_lines(dw):
    lines = dw.format_output_lines({"status": "success", "deployment_url": "https://x"})
    assert lines == "status=success\ndeployment_url=https://x\n"


def test_format_output_lines_empty(dw):
    assert dw.format_output_lines({}) == ""


def test_render_step_variants(dw):
    assert dw.render_step({"name": "Deploy", "status": "in_progress"}) == "  Running step: Deploy..."
    assert dw.render_step({"name": "Deploy", "status": "completed", "conclusion": "success"}) == "  [ok] Deploy"
    assert dw.render_step({"name": "Deploy", "status": "completed", "conclusion": "failure"}) == "  [FAILED] Deploy"
    assert dw.render_step({"name": "Deploy", "status": "queued"}) is None


def test_render_step_completed_without_conclusion_is_failed(dw):
    assert dw.render_step({"name": "Deploy", "status": "completed"}) == "  [FAILED] Deploy"


def test_step_key_is_unique_per_transition(dw):
    job = {"id": 7}
    a = dw.step_key(job, {"name": "Deploy", "status": "in_progress"})
    b = dw.step_key(job, {"name": "Deploy", "status": "completed"})
    assert a != b
