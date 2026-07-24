"""Unit tests for dispatch_and_wait.py. The script ships with the composite
action (it lives outside the cloudapp package), so it is loaded by path. Pure
helpers are tested directly; the network stages are tested with urllib.urlopen
monkeypatched (see HttpMock), so no real HTTP happens."""

import importlib.util
import io
import json
import urllib.error
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


class _Resp:
    """Fake urlopen response / context manager. Wraps JSON (dict/list) or bytes."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode() if isinstance(payload, (dict, list)) else payload

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class HttpMock:
    """Routes urlopen by a substring of the request URL. Each route maps to a
    list of responses (or Exceptions) consumed in order; a single entry repeats.
    Records every Request for assertions."""

    def __init__(self, routes):
        self.routes = {key: list(vals) for key, vals in routes.items()}
        self.requests = []

    def __call__(self, req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else req
        self.requests.append(req)
        for key, responses in self.routes.items():
            if key in url:
                result = responses[0] if len(responses) == 1 else responses.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture
def no_sleep(dw, monkeypatch):
    monkeypatch.setattr(dw.time, "sleep", lambda *_: None)


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


# --- Network stages (urllib.urlopen monkeypatched) ---

def _zip_results(results):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("deployment-results.json", json.dumps(results))
    return buf.getvalue()


def test_dispatch_run_posts_payload_and_returns_ids(dw, monkeypatch):
    mock = HttpMock({"/dispatches": [_Resp({"workflow_run_id": 99, "html_url": "https://run/99"})]})
    monkeypatch.setattr(dw.urllib.request, "urlopen", mock)

    run_id, html = dw.dispatch_run(
        "https://api.github.com/repos/acme/orders", "deploy.yml", "main", {"env": "dev"}, dw.build_headers("t"))

    assert (run_id, html) == (99, "https://run/99")
    req = mock.requests[0]
    assert req.method == "POST"
    assert req.full_url == "https://api.github.com/repos/acme/orders/actions/workflows/deploy.yml/dispatches"
    assert json.loads(req.data) == {"ref": "main", "inputs": {"env": "dev"}, "return_run_details": True}


def test_dispatch_run_exits_on_http_error(dw, monkeypatch):
    err = urllib.error.HTTPError("u", 422, "unprocessable", None, io.BytesIO(b"bad ref"))
    monkeypatch.setattr(dw.urllib.request, "urlopen", HttpMock({"/dispatches": [err]}))
    with pytest.raises(SystemExit) as exc:
        dw.dispatch_run("https://api.github.com/repos/acme/orders", "deploy.yml", "main", {}, dw.build_headers("t"))
    assert exc.value.code == 1


def test_expose_deployment_outputs_writes_to_github_output(dw, tmp_path, monkeypatch):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    run_api = "https://api.github.com/repos/acme/orders/actions/runs/7"
    mock = HttpMock({
        "/artifacts": [_Resp({"artifacts": [{"name": "deployment-outputs-7", "archive_download_url": "https://dl/7"}]})],
        "https://dl/7": [_Resp(_zip_results({"status": "success", "deployment_url": "https://x"}))],
    })
    monkeypatch.setattr(dw.urllib.request, "urlopen", mock)

    dw.expose_deployment_outputs(run_api, 7, dw.build_headers("t"))

    assert out.read_text() == "status=success\ndeployment_url=https://x\n"


def test_expose_deployment_outputs_noop_without_github_output(dw, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    # urlopen left unpatched: if it were called, the missing route/network would error.
    mock = HttpMock({})
    monkeypatch.setattr(dw.urllib.request, "urlopen", mock)
    dw.expose_deployment_outputs("https://api.github.com/repos/acme/orders/actions/runs/7", 7, dw.build_headers("t"))
    assert mock.requests == []


def test_expose_deployment_outputs_warns_when_artifact_absent(dw, tmp_path, monkeypatch):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    mock = HttpMock({"/artifacts": [_Resp({"artifacts": [{"name": "something-else"}]})]})
    monkeypatch.setattr(dw.urllib.request, "urlopen", mock)
    dw.expose_deployment_outputs("https://api.github.com/repos/acme/orders/actions/runs/7", 7, dw.build_headers("t"))
    assert not out.exists()  # nothing written


def test_wait_for_completion_polls_until_done(dw, monkeypatch, no_sleep):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)  # skip output export
    mock = HttpMock({
        "/jobs": [_Resp({"jobs": []})],  # matched before /runs/7 (substring order)
        "/runs/7": [_Resp({"status": "in_progress"}), _Resp({"status": "completed", "conclusion": "success"})],
    })
    monkeypatch.setattr(dw.urllib.request, "urlopen", mock)

    assert dw.wait_for_completion("https://api.github.com/repos/acme/orders", 7, dw.build_headers("t")) == "success"


def test_wait_for_completion_exits_on_auth_error(dw, monkeypatch):
    err = urllib.error.HTTPError("u", 401, "unauthorized", None, io.BytesIO(b""))
    monkeypatch.setattr(dw.urllib.request, "urlopen", HttpMock({"/runs/7": [err]}))
    with pytest.raises(SystemExit) as exc:
        dw.wait_for_completion("https://api.github.com/repos/acme/orders", 7, dw.build_headers("t"))
    assert exc.value.code == 1
