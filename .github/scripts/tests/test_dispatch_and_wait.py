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


def test_build_headers(dw):
    assert dw.build_headers("secret") == {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer secret",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def test_url_builders(dw):
    assert dw.dispatches_url("acme", "orders", "deploy.yml") == \
        "https://api.github.com/repos/acme/orders/actions/workflows/deploy.yml/dispatches"
    assert dw.run_url("acme", "orders", 42) == "https://api.github.com/repos/acme/orders/actions/runs/42"
    assert dw.jobs_url("acme", "orders", 42) == "https://api.github.com/repos/acme/orders/actions/runs/42/jobs"
    assert dw.artifacts_url("acme", "orders", 42) == \
        "https://api.github.com/repos/acme/orders/actions/runs/42/artifacts"


@pytest.mark.parametrize("code", [401, 403])
def test_poll_error_action_auth_regardless_of_count(dw, code):
    assert dw.poll_error_action(code, 1, 6) == "auth"
    assert dw.poll_error_action(code, 99, 6) == "auth"


def test_poll_error_action_retry_below_limit(dw):
    assert dw.poll_error_action(404, 3, 6) == "retry"


def test_poll_error_action_giveup_at_limit(dw):
    assert dw.poll_error_action(500, 6, 6) == "giveup"


def test_status_line_queued_is_annotated(dw):
    assert dw.status_line("queued") == "Status: queued (waiting for concurrent deployment lock)..."


def test_status_line_other(dw):
    assert dw.status_line("in_progress") == "Status: in_progress..."


def test_collect_step_lines_dedups_and_skips_unprintable(dw):
    seen = set()
    jobs = {"jobs": [{"id": 1, "steps": [
        {"name": "Build", "status": "in_progress"},
        {"name": "Wait", "status": "queued"},  # render_step -> None, skipped
    ]}]}
    assert dw.collect_step_lines(jobs, seen) == ["  Running step: Build..."]
    # Same payload again: every step already seen -> nothing new.
    assert dw.collect_step_lines(jobs, seen) == []


def test_collect_step_lines_empty_jobs(dw):
    assert dw.collect_step_lines({}, set()) == []
