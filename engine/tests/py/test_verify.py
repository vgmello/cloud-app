import pytest

from cloudapp import verify


class _Res:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Clock:
    """Fake clock: sleeping advances time, so deadline logic is deterministic."""

    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


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


def test_check_resource_unknown_running_state_is_not_failed():
    # runningState is extensible; a new healthy value must not fail the check
    run = _runner([
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Provisioned", "running": "RunningAtMaxScale"}'),
    ])
    res = {"kind": "containerapp", "name": "ca-orders-api-dev", "require_running": True}
    state, _ = verify.check_resource(res, "rg-x", run)
    assert state == verify.HEALTHY


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


def test_check_resource_function_empty_output_is_terminal():
    # az functionapp show can exit 0 with empty output for a nonexistent site;
    # an existing site always reports a state, so this must not poll to timeout.
    run = _runner([_Res(0, "")])
    res = {"kind": "functionapp", "name": "func-orders-api-dev", "require_running": True}
    state, detail = verify.check_resource(res, "rg-x", run)
    assert state == verify.FAILED
    assert "not found" in detail.lower()


ONE_APP = {"name": "orders-api", "apps": {"api": {"replicas": {"min": 1}}}, "functions": {}}


def test_verify_passes_when_healthy_immediately():
    run = _runner([
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Provisioned", "running": "Running"}'),
    ])
    clock = _Clock()
    n = verify.verify(ONE_APP, "", "dev", "rg-x", run, timeout=300,
                       sleep=clock.sleep, now=clock.now)
    assert n == 1
    assert clock.slept == []


def test_verify_retries_until_healthy():
    run = _runner([
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Provisioning", "running": "Processing"}'),
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Provisioned", "running": "Running"}'),
    ])
    clock = _Clock()
    n = verify.verify(ONE_APP, "", "dev", "rg-x", run, timeout=300,
                       sleep=clock.sleep, now=clock.now)
    assert n == 1
    assert clock.slept == [10]


def test_verify_raises_when_budget_exhausted():
    def run(cmd, check=False, capture=False):
        if "revision" in cmd:
            return _Res(0, '{"prov": "Provisioned", "running": "Processing"}')
        return _Res(0, "rev1\n")

    clock = _Clock()
    with pytest.raises(verify.VerifyError, match="ca-orders-api-dev"):
        verify.verify(ONE_APP, "", "dev", "rg-x", run, timeout=30,
                       sleep=clock.sleep, now=clock.now)
    # timeout=30, interval=10 -> the deadline is polled after every round rather
    # than a fixed attempt count, so the loop probes once more than the old
    # attempt-count logic (4 rounds) but each sleep is capped to the remaining
    # budget, so it still stops exactly at the 30s deadline: 3 sleeps of 10.
    assert clock.slept == [10, 10, 10]
    assert clock.t == 30


def test_verify_fails_fast_on_terminal_state():
    clock = _Clock()
    run = _runner([
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Failed", "running": "Stopped"}'),
    ])
    with pytest.raises(verify.VerifyError, match="ca-orders-api-dev"):
        verify.verify(ONE_APP, "", "dev", "rg-x", run, timeout=300,
                       sleep=clock.sleep, now=clock.now)
    assert clock.slept == []  # did not burn the poll budget


def test_verify_missing_app_reports_incomplete_stack():
    run = _runner([_Res(1, "", "ResourceNotFound")])
    clock = _Clock()
    with pytest.raises(verify.VerifyError, match="incomplete"):
        verify.verify(ONE_APP, "", "dev", "rg-x", run, timeout=300,
                       sleep=clock.sleep, now=clock.now)


def test_verify_no_resources_is_noop():
    tool = {"name": "site", "apps": {}, "functions": {}}
    run = _runner([])
    clock = _Clock()
    assert verify.verify(tool, "", "dev", "rg-x", run, sleep=clock.sleep, now=clock.now) == 0
    assert run.calls == []


def test_verify_multi_resource_waits_for_all_and_skips_healthy():
    tool = {
        "name": "orders-api",
        "apps": {
            "fast": {"replicas": {"min": 1}},
            "slow": {"replicas": {"min": 1}},
        },
        "functions": {},
    }
    fast = "ca-orders-api-fast-dev"
    slow = "ca-orders-api-slow-dev"
    calls = []
    rounds = {"slow": 0}

    def run(cmd, check=False, capture=False):
        calls.append(cmd)
        name = fast if fast in cmd else slow
        if "revision" not in cmd:
            return _Res(0, "rev1\n")
        if name == fast:
            return _Res(0, '{"prov": "Provisioned", "running": "Running"}')
        rounds["slow"] += 1
        if rounds["slow"] == 1:
            return _Res(0, '{"prov": "Provisioning", "running": "Processing"}')
        return _Res(0, '{"prov": "Provisioned", "running": "Running"}')

    clock = _Clock()
    n = verify.verify(tool, "", "dev", "rg-x", run, timeout=300,
                       sleep=clock.sleep, now=clock.now)

    assert n == 2
    assert clock.slept == [10]
    fast_probes = sum(1 for c in calls if fast in c)
    slow_probes = sum(1 for c in calls if slow in c)
    assert fast_probes == 2, "healthy resource must not be re-probed"
    assert slow_probes == 4, "pending resource must be re-probed each round"


def test_verify_fails_when_one_resource_is_terminal_though_another_is_healthy():
    tool = {
        "name": "orders-api",
        "apps": {"good": {"replicas": {"min": 1}}, "bad": {"replicas": {"min": 1}}},
        "functions": {},
    }

    def run(cmd, check=False, capture=False):
        if "revision" not in cmd:
            return _Res(0, "rev1\n")
        if "bad" in " ".join(cmd):
            return _Res(0, '{"prov": "Failed", "running": "Stopped"}')
        return _Res(0, '{"prov": "Provisioned", "running": "Running"}')

    clock = _Clock()
    with pytest.raises(verify.VerifyError, match="bad"):
        verify.verify(tool, "", "dev", "rg-x", run, timeout=300,
                       sleep=clock.sleep, now=clock.now)
    assert clock.slept == []
