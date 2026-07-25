from cloudapp import verify


class _Res:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


TOOL = {
    "name": "orders-api",
    "apps": {
        "api": {"replicas": {"min": 1, "max": 3}},
        "worker": {"replicas": {"min": 0, "max": 2}},
    },
    "functions": {"processor": {}},
}


def _runner(results):
    """Fake run: pops a queued result per call, recording the commands."""
    calls = []
    queue = list(results)

    def run(cmd, check=False, capture=False):
        calls.append(cmd)
        return queue.pop(0) if queue else _Res(0, "")

    run.calls = calls
    return run


def test_expected_resources_covers_apps_and_functions():
    got = verify.expected_resources(TOOL, "", "dev")
    by_name = {r["name"]: r for r in got}
    assert set(by_name) == {
        "ca-orders-api-api-dev",
        "ca-orders-api-worker-dev",
        "func-orders-api-dev",
    }
    assert by_name["ca-orders-api-api-dev"]["kind"] == "containerapp"
    assert by_name["func-orders-api-dev"]["kind"] == "functionapp"


def test_expected_resources_scale_to_zero_does_not_require_running():
    by_name = {r["name"]: r for r in verify.expected_resources(TOOL, "", "dev")}
    assert by_name["ca-orders-api-api-dev"]["require_running"] is True
    assert by_name["ca-orders-api-worker-dev"]["require_running"] is False


def test_expected_resources_functions_always_require_running():
    by_name = {r["name"]: r for r in verify.expected_resources(TOOL, "", "dev")}
    assert by_name["func-orders-api-dev"]["require_running"] is True


def test_expected_resources_skips_static_sites():
    tool = {"name": "site", "apps": {}, "functions": {}, "static_sites": {"web": {}}}
    assert verify.expected_resources(tool, "", "dev") == []


def test_expected_resources_missing_replicas_requires_running():
    # unspecified replicas means always-on (manifest.REPLICA_DEFAULTS min=1),
    # so the check must fail closed rather than skip the running requirement
    tool = {"name": "orders-api", "apps": {"api": {}}, "functions": {}}
    got = verify.expected_resources(tool, "", "dev")
    assert got[0]["require_running"] is True


def test_check_resource_healthy_container_app():
    run = _runner([
        _Res(0, "ca-orders-api-dev--abc123\n"),
        _Res(0, '{"prov": "Provisioned", "running": "Running"}'),
    ])
    res = {"kind": "containerapp", "name": "ca-orders-api-dev", "require_running": True}
    state, _ = verify.check_resource(res, "rg-x", run)
    assert state == verify.HEALTHY
    # the revision parsed from the first probe must be the one queried
    assert run.calls[1][:4] == ["az", "containerapp", "revision", "show"]
    assert "ca-orders-api-dev--abc123" in run.calls[1]


def test_check_resource_missing_app_is_terminal():
    run = _runner([_Res(1, "", "ResourceNotFound: was not found")])
    res = {"kind": "containerapp", "name": "ca-orders-api-dev", "require_running": True}
    state, detail = verify.check_resource(res, "rg-x", run)
    assert state == verify.FAILED
    assert "not found" in detail.lower()


def test_check_resource_transient_az_error_retries():
    run = _runner([_Res(1, "", "temporary network glitch")])
    res = {"kind": "containerapp", "name": "ca-orders-api-dev", "require_running": True}
    state, _ = verify.check_resource(res, "rg-x", run)
    assert state == verify.PENDING


def test_check_resource_failed_provisioning_is_terminal():
    run = _runner([
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Failed", "running": "Stopped"}'),
    ])
    res = {"kind": "containerapp", "name": "ca-orders-api-dev", "require_running": True}
    state, _ = verify.check_resource(res, "rg-x", run)
    assert state == verify.FAILED


def test_check_resource_idle_app_passes_when_running_not_required():
    run = _runner([
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Provisioned", "running": "Stopped"}'),
    ])
    res = {"kind": "containerapp", "name": "ca-orders-api-worker-dev", "require_running": False}
    state, _ = verify.check_resource(res, "rg-x", run)
    assert state == verify.HEALTHY


def test_check_resource_not_running_is_pending_when_required():
    run = _runner([
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Provisioned", "running": "Processing"}'),
    ])
    res = {"kind": "containerapp", "name": "ca-orders-api-dev", "require_running": True}
    state, _ = verify.check_resource(res, "rg-x", run)
    assert state == verify.PENDING


def test_check_resource_function_running_passes():
    run = _runner([_Res(0, "Running\n")])
    res = {"kind": "functionapp", "name": "func-orders-api-dev", "require_running": True}
    state, _ = verify.check_resource(res, "rg-x", run)
    assert state == verify.HEALTHY
    assert run.calls[0][:2] == ["az", "functionapp"]


def test_check_resource_function_stopped_is_pending():
    run = _runner([_Res(0, "Stopped\n")])
    res = {"kind": "functionapp", "name": "func-orders-api-dev", "require_running": True}
    state, _ = verify.check_resource(res, "rg-x", run)
    assert state == verify.PENDING
