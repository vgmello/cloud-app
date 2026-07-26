# Post-Deploy Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a deploy, verify against Azure that the manifest's container apps and function apps exist and are healthy; fail the run when they are not.

**Architecture:** A new engine module `verify.py` (pure `expected_resources`, a single-probe `check_resource`, and a polling `verify`) behind a `cloudapp verify-deploy` CLI command, invoked by a new `Verify deployment` action step that runs after both deploy lanes.

**Tech Stack:** Python engine (`engine/cloudapp/`), Azure CLI, GitHub Actions composite action, pytest.

## Global Constraints

- Resource names come from the existing `naming.container_app_name` / `naming.function_app_name` helpers — never re-derived.
- `replicas.min == 0` apps must pass when provisioned but idle; only `replicas.min > 0` requires `runningState == "Running"`.
- Failure must be terminal-aware: `provisioningState == "Failed"` fails immediately rather than burning the poll budget; a transient `az` error retries.
- All `az` access goes through the injected `run` seam — `run(cmd_list, check=False, capture=True)` returning `.returncode` / `.stdout` / `.stderr` — exactly as `rotate.py` and `backend.py` do. No `shell=True`, argv lists only.
- Defaults: `verify_deploy` = `"true"`, `verify_timeout` = `"300"`, poll interval 10s.
- `VerifyError` must be added to the caught-exception tuple in `cli.main` so failures render as `::error::`, not tracebacks.
- Tests: `cd engine && python3 -m pytest`; lint `python3 -m ruff check .` (invoke via `python3 -m`).

---

### Task 1: `verify.py` — expected resources + single-resource probe

**Files:**

- Create: `engine/cloudapp/verify.py`
- Test: `engine/tests/py/test_verify.py`

**Interfaces:**

- Produces: `verify.VerifyError` (Exception).
- Produces: `verify.HEALTHY` / `verify.PENDING` / `verify.FAILED` — the three state constants (strings).
- Produces: `verify.expected_resources(tool: dict, prefix: str, env: str) -> list[dict]` — one entry per verifiable resource: `{"kind": "containerapp"|"functionapp", "name": str, "require_running": bool}`.
- Produces: `verify.check_resource(resource: dict, resource_group: str, run) -> tuple[str, str]` — `(state, detail)` where state is one of the three constants. _(This refines the spec's `(healthy, detail)` into a tri-state so terminal failures can fail fast.)_

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/py/test_verify.py`:

```python
import pytest

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


def test_check_resource_healthy_container_app():
    run = _runner([
        _Res(0, "ca-orders-api-dev--abc123\n"),
        _Res(0, '{"prov": "Provisioned", "running": "Running"}'),
    ])
    res = {"kind": "containerapp", "name": "ca-orders-api-dev", "require_running": True}
    state, _ = verify.check_resource(res, "rg-x", run)
    assert state == verify.HEALTHY


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cloudapp.verify'`.

- [ ] **Step 3: Implement `verify.py` (this task's half)**

Create `engine/cloudapp/verify.py`:

```python
"""Post-deploy verification: do the manifest's resources exist and are they healthy?

Checks reality rather than a derived signal. Runs after both deploy lanes — the
Terraform apply and the direct image rotation — and even when neither changed
anything, which is what makes a half-built stack loud instead of silently green.
"""

import json
import re

from . import naming

NOT_FOUND = re.compile(r"ResourceNotFound|was not found|could not be found", re.IGNORECASE)

HEALTHY = "healthy"
PENDING = "pending"
FAILED = "failed"


class VerifyError(Exception):
    pass


def expected_resources(tool, prefix, env):
    """Every resource the manifest declares that can be health-checked.

    Static sites are excluded: no revisions and no image. A container app only
    has to be *running* when it declares at least one replica — a scale-to-zero
    app is legitimately idle and must not fail the check.
    """
    resources = []
    for app_key, app in (tool.get("apps") or {}).items():
        replicas = app.get("replicas") or {}
        resources.append({
            "kind": "containerapp",
            "name": naming.container_app_name(tool, prefix, env, app_key),
            "require_running": (replicas.get("min") or 0) > 0,
        })
    for func_key in (tool.get("functions") or {}):
        resources.append({
            "kind": "functionapp",
            "name": naming.function_app_name(tool, prefix, env, func_key),
            "require_running": True,
        })
    return resources


def _az(run, cmd):
    """Run an az query; classify a failure as terminal (not-found) or transient."""
    result = run(cmd, check=False, capture=True)
    if result.returncode == 0:
        return None, (result.stdout or "").strip()
    stderr = result.stderr or ""
    if NOT_FOUND.search(stderr):
        return FAILED, "not found (the stack may be incomplete)"
    return PENDING, f"az query failed: {stderr.strip()[:200]}"


def _check_container_app(resource, resource_group, run):
    state, out = _az(run, [
        "az", "containerapp", "show",
        "--name", resource["name"], "--resource-group", resource_group,
        "--query", "properties.latestRevisionName", "-o", "tsv",
    ])
    if state:
        return state, out
    revision = out
    if not revision:
        return PENDING, "no revision yet"

    state, out = _az(run, [
        "az", "containerapp", "revision", "show",
        "--name", resource["name"], "--resource-group", resource_group,
        "--revision", revision,
        "--query", "{prov:properties.provisioningState,running:properties.runningState}",
        "-o", "json",
    ])
    if state:
        return state, out
    try:
        states = json.loads(out or "{}")
    except ValueError:
        return PENDING, f"unparseable revision state for {revision}"

    prov = states.get("prov") or "unknown"
    running = states.get("running") or "unknown"
    detail = f"revision {revision} provisioningState={prov} runningState={running}"
    if prov == "Failed" or running == "Failed":
        return FAILED, detail
    if prov != "Provisioned":
        return PENDING, detail
    if resource["require_running"] and running != "Running":
        return PENDING, detail
    return HEALTHY, detail


def _check_function_app(resource, resource_group, run):
    state, out = _az(run, [
        "az", "functionapp", "show",
        "--name", resource["name"], "--resource-group", resource_group,
        "--query", "state", "-o", "tsv",
    ])
    if state:
        return state, out
    detail = f"state={out or 'unknown'}"
    return (HEALTHY, detail) if out == "Running" else (PENDING, detail)


def check_resource(resource, resource_group, run):
    """One probe of one resource. Returns (state, human-readable detail)."""
    if resource["kind"] == "containerapp":
        return _check_container_app(resource, resource_group, run)
    return _check_function_app(resource, resource_group, run)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engine && python3 -m pytest tests/py/test_verify.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Lint**

Run: `cd engine && python3 -m ruff check cloudapp/verify.py tests/py/test_verify.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/verify.py engine/tests/py/test_verify.py
git commit -m "feat(verify): expected resources and single-resource health probe"
```

---

### Task 2: `verify()` — the polling loop

**Files:**

- Modify: `engine/cloudapp/verify.py` (append `verify`)
- Test: `engine/tests/py/test_verify.py`

**Interfaces:**

- Consumes: `expected_resources`, `check_resource`, the state constants, `VerifyError` (Task 1).
- Produces: `verify.verify(tool, prefix, env, resource_group, run, timeout=300, sleep=time.sleep, interval=10) -> int` — returns the number of verified resources; raises `VerifyError` on terminal failure or budget exhaustion.

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/py/test_verify.py`:

```python
ONE_APP = {"name": "orders-api", "apps": {"api": {"replicas": {"min": 1}}}, "functions": {}}


def test_verify_passes_when_healthy_immediately():
    run = _runner([
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Provisioned", "running": "Running"}'),
    ])
    slept = []
    n = verify.verify(ONE_APP, "", "dev", "rg-x", run, timeout=300, sleep=slept.append)
    assert n == 1
    assert slept == []


def test_verify_retries_until_healthy():
    run = _runner([
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Provisioning", "running": "Processing"}'),
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Provisioned", "running": "Running"}'),
    ])
    slept = []
    n = verify.verify(ONE_APP, "", "dev", "rg-x", run, timeout=300, sleep=slept.append)
    assert n == 1
    assert slept == [10]


def test_verify_raises_when_budget_exhausted():
    def run(cmd, check=False, capture=False):
        if "revision" in cmd:
            return _Res(0, '{"prov": "Provisioned", "running": "Processing"}')
        return _Res(0, "rev1\n")

    with pytest.raises(verify.VerifyError, match="ca-orders-api-dev"):
        verify.verify(ONE_APP, "", "dev", "rg-x", run, timeout=30, sleep=lambda _: None)


def test_verify_fails_fast_on_terminal_state():
    slept = []
    run = _runner([
        _Res(0, "rev1\n"),
        _Res(0, '{"prov": "Failed", "running": "Stopped"}'),
    ])
    with pytest.raises(verify.VerifyError, match="ca-orders-api-dev"):
        verify.verify(ONE_APP, "", "dev", "rg-x", run, timeout=300, sleep=slept.append)
    assert slept == []  # did not burn the poll budget


def test_verify_missing_app_reports_incomplete_stack():
    run = _runner([_Res(1, "", "ResourceNotFound")])
    with pytest.raises(verify.VerifyError, match="incomplete"):
        verify.verify(ONE_APP, "", "dev", "rg-x", run, timeout=300, sleep=lambda _: None)


def test_verify_no_resources_is_noop():
    tool = {"name": "site", "apps": {}, "functions": {}}
    run = _runner([])
    assert verify.verify(tool, "", "dev", "rg-x", run, sleep=lambda _: None) == 0
    assert run.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_verify.py -k verify_ -v`
Expected: FAIL — `AttributeError: module 'cloudapp.verify' has no attribute 'verify'`.

- [ ] **Step 3: Implement the polling loop**

Add `import time` to the imports at the top of `engine/cloudapp/verify.py` (beside `import json` and `import re`), add the interval constant next to the state constants:

```python
POLL_INTERVAL = 10
```

and append this function to the end of the file:

```python
def verify(tool, prefix, env, resource_group, run, timeout=300, sleep=time.sleep,
           interval=POLL_INTERVAL):
    """Poll every declared resource until all are healthy or the budget expires.

    Raises VerifyError as soon as any resource reaches a terminal state, so a
    genuinely broken deploy fails fast instead of waiting out the timeout.
    """
    resources = expected_resources(tool, prefix, env)
    if not resources:
        print("no verifiable resources declared")
        return 0

    attempts = max(1, int(timeout // interval))
    pending = list(resources)
    details = {}
    for attempt in range(1, attempts + 1):
        still_pending = []
        for resource in pending:
            state, detail = check_resource(resource, resource_group, run)
            details[resource["name"]] = detail
            if state == FAILED:
                raise VerifyError(f"{resource['name']}: {detail}")
            if state != HEALTHY:
                still_pending.append(resource)
            else:
                print(f"verified {resource['name']} ({detail})")
        pending = still_pending
        if not pending:
            print(f"verified {len(resources)} resource(s)")
            return len(resources)
        if attempt < attempts:
            sleep(interval)

    unhealthy = ", ".join(f"{r['name']} [{details.get(r['name'], 'unknown')}]" for r in pending)
    raise VerifyError(
        f"not healthy after {timeout}s: {unhealthy}. "
        "Check the container logs; if the stack is incomplete, re-run with "
        "always_run_terraform: true."
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engine && python3 -m pytest tests/py/test_verify.py -v`
Expected: PASS (18 tests).

- [ ] **Step 5: Lint + full suite**

Run: `cd engine && python3 -m pytest -q && python3 -m ruff check .`
Expected: full suite green; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/verify.py engine/tests/py/test_verify.py
git commit -m "feat(verify): poll declared resources until healthy or budget expires"
```

---

### Task 3: `verify-deploy` CLI command

**Files:**

- Modify: `engine/cloudapp/cli.py`
- Test: `engine/tests/py/test_cli.py`

**Interfaces:**

- Consumes: `verify.verify`, `verify.VerifyError` (Tasks 1-2).
- Produces: CLI `python -m cloudapp verify-deploy --tool-json --environment --platform-file --resource-group [--timeout]`.

- [ ] **Step 1: Write the failing test**

Add to `engine/tests/py/test_cli.py`:

```python
def test_verify_deploy_cli_probes_the_expected_app(tmp_path, monkeypatch):
    import json as _json

    from cloudapp import cli, runner

    tool = {"name": "orders-api", "apps": {"api": {"replicas": {"min": 1}}}, "functions": {}}
    (tmp_path / "tool.dev.json").write_text(_json.dumps(tool))
    (tmp_path / "dev.yml").write_text('naming_prefix: ""\nstate_backend:\n  type: azurerm\n')

    calls = []

    class _R:
        returncode = 0
        stderr = ""

        def __init__(self, stdout=""):
            self.stdout = stdout

    def fake_run(cmd, check=False, capture=False):
        calls.append(cmd)
        if "revision" in cmd:
            return _R('{"prov": "Provisioned", "running": "Running"}')
        return _R("rev1\n")

    monkeypatch.setattr(runner, "run", fake_run)

    cli.main([
        "verify-deploy",
        "--tool-json", str(tmp_path / "tool.dev.json"),
        "--environment", "dev",
        "--platform-file", str(tmp_path / "dev.yml"),
        "--resource-group", "rg-x",
    ])

    assert calls[0][:3] == ["az", "containerapp", "show"]
    assert "ca-orders-api-dev" in calls[0]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd engine && python3 -m pytest tests/py/test_cli.py::test_verify_deploy_cli_probes_the_expected_app -v`
Expected: FAIL — `argument command: invalid choice: 'verify-deploy'`.

- [ ] **Step 3: Wire the command**

In `engine/cloudapp/cli.py`, add `verify` to the module import tuple (alphabetical: after `tfdeploy`):

```python
from . import (
    backend,
    builds,
    customtf,
    dockerbuild,
    gha,
    identity,
    manifest,
    registry,
    resolve,
    rotate,
    runner,
    secrets,
    tfdeploy,
    verify,
)
```

(Keep whatever entries already exist; just add `verify` in alphabetical position.)

Add the command function next to `cmd_rotate_images`:

```python
def cmd_verify_deploy(args):
    tool = _load_json(args.tool_json)
    platform = _load_platform(args.platform_file)
    prefix = platform.get("naming_prefix") or ""
    verify.verify(
        tool, prefix, args.environment, args.resource_group, runner.run,
        timeout=args.timeout,
    )
```

- [ ] **Step 4: Register the subparser and the exception**

Add the subparser next to the `rotate-images` one:

```python
    p = sub.add_parser("verify-deploy")
    p.add_argument("--tool-json", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--platform-file", required=True)
    p.add_argument("--resource-group", required=True)
    p.add_argument("--timeout", type=int, default=300)
    p.set_defaults(func=cmd_verify_deploy)
```

Add `verify.VerifyError` to the caught-exception tuple in `main`:

```python
    except (manifest.ManifestError, resolve.ResolveError, secrets.SyncError,
            tfdeploy.DeployError, backend.BackendError, rotate.RotateError,
            customtf.CustomTfError, verify.VerifyError,
            registry.RegistryError, ValueError) as exc:
        gha.error(str(exc))
```

(Preserve every exception already in the tuple; only add `verify.VerifyError`.)

- [ ] **Step 5: Run the test, full suite, and lint**

Run: `cd engine && python3 -m pytest -q && python3 -m ruff check .`
Expected: full suite green; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/cli.py engine/tests/py/test_cli.py
git commit -m "feat(cli): verify-deploy command"
```

---

### Task 4: Action step, recovery flag, and docs

**Files:**

- Modify: `.github/actions/cloud-app/action.yml`
- Modify: `samples/caller-app/.github/workflows/cloud-app.yml`
- Modify: `samples/caller-app/README.md`, `docs/usage.md`

**Interfaces:**

- Consumes: `python -m cloudapp verify-deploy` (Task 3); existing step outputs `steps.parse.outputs.name`, `steps.platform.outputs.file`, `steps.bootstrap.outputs.resource_group`.

- [ ] **Step 1: Add the two inputs**

In `.github/actions/cloud-app/action.yml`, add to the `inputs:` block (after `always_run_terraform`):

```yaml
verify_deploy:
  description: >-
    After deploying, check that the manifest's container apps and function
    apps exist and are healthy, failing the run when they are not. This is
    what makes a half-built stack or a crash-looping image loud instead of
    silently green. Set to "false" to skip.
  default: "true"
verify_timeout:
  description: Seconds to wait for every resource to become healthy.
  default: "300"
```

- [ ] **Step 2: Add the verification step**

In the same file, add this step immediately **after** the `Terraform deploy` step and **before** `Write summary`. It deliberately runs on both lanes and even when neither deployed anything:

```yaml
# Reality check, not bookkeeping: confirm the declared resources exist and
# are healthy. Runs after BOTH lanes — and even when neither changed
# anything — so a half-built stack cannot report success.
- name: Verify deployment
  if: ${{ inputs.plan_only == 'false' && inputs.verify_deploy != 'false' }}
  shell: bash
  env:
    DEPLOY_ENV: ${{ inputs.env }}
    VERIFY_TIMEOUT: ${{ inputs.verify_timeout }}
  run: >-
    PYTHONPATH="${{ github.action_path }}/../../../engine"
    python3 -m cloudapp verify-deploy
    --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
    --environment "$DEPLOY_ENV"
    --platform-file "${{ steps.platform.outputs.file }}"
    --resource-group "${{ steps.bootstrap.outputs.resource_group }}"
    --timeout "$VERIFY_TIMEOUT"
```

- [ ] **Step 3: Add the recovery lever to the sample workflow**

In `samples/caller-app/.github/workflows/cloud-app.yml`, add a boolean input to the existing `workflow_dispatch.inputs` block:

```yaml
always_run_terraform:
  description: Force a full Terraform run (use to recover an incomplete deploy)
  type: boolean
  default: false
```

and pass it to the action, alongside the existing `with:` entries:

```yaml
always_run_terraform: ${{ inputs.always_run_terraform || false }}
```

- [ ] **Step 4: Validate the YAML**

Run:

```bash
cd /Users/vgmello-dev/repos/projects/deploy
python3 -c "import yaml; yaml.safe_load(open('.github/actions/cloud-app/action.yml')); print('action OK')"
python3 -c "import yaml; yaml.safe_load(open('samples/caller-app/.github/workflows/cloud-app.yml')); print('sample OK')"
grep -n "name: Terraform deploy\|name: Verify deployment\|name: Write summary" .github/actions/cloud-app/action.yml
```

Expected: both print OK; the three step names appear in the order `Terraform deploy`, `Verify deployment`, `Write summary`.

- [ ] **Step 5: Document verification and recovery**

In `samples/caller-app/README.md`, add a short section after the "How it works" list:

```markdown
## When a deploy fails verification

After deploying, the action checks that every container app and function app in
the manifest exists and is healthy, and fails the run if not. Two common causes:

- **A crash-looping image.** The deploy succeeded but the new revision is
  unhealthy — check the container logs for that revision (the error names it).
- **An incomplete stack.** An earlier deploy failed partway, so a resource was
  never created. Re-run the workflow manually with `always_run_terraform: true`
  to force a full Terraform run and finish the stack.

Set `verify_deploy: false` on the action to skip the check.
```

In `docs/usage.md`, add the same two bullets in condensed form under the notes section, and mention that `always_run_terraform: true` (or a manual dispatch) forces a full Terraform run.

- [ ] **Step 6: Commit**

```bash
git add .github/actions/cloud-app/action.yml samples/caller-app docs/usage.md
git commit -m "feat(cloud-app): verify deployment health; add recovery flag to the sample"
```

---

## Self-Review

**Spec coverage:**

- Runs after both lanes and when neither deployed → Task 4 Step 2 (no gate condition, only `plan_only`/`verify_deploy`). ✓
- Container apps: exist + latest revision provisioned; running required only when `replicas.min > 0` → Task 1 (`expected_resources`, `_check_container_app`). ✓
- Function apps: exist + `Running` → Task 1 (`_check_function_app`). ✓
- Static sites skipped → Task 1 test `test_expected_resources_skips_static_sites`. ✓
- Polling every 10s up to `verify_timeout` (default 300) → Task 2. ✓
- Fail fast on terminal `Failed`; transient `az` errors retry → Task 1 `_az`, Task 2 loop; tested both. ✓
- Error names resource, revision, and state → Task 2 message + `detail` strings. ✓
- `verify_deploy` / `verify_timeout` inputs → Task 4 Step 1. ✓
- `VerifyError` in the CLI exception tuple → Task 3 Step 4. ✓
- `always_run_terraform` dispatch input in the sample → Task 4 Step 3. ✓
- Docs for failure meaning + recovery → Task 4 Step 5. ✓
- Names via `naming` helpers → Task 1 `expected_resources`. ✓

**Placeholder scan:** No TBD/TODO. Every code block is complete. Task 4 Step 5's second paragraph ("same two bullets in condensed form") targets a doc file the implementer has open, with the content given directly above it.

**Type consistency:** `expected_resources(tool, prefix, env) -> list[dict]` with keys `kind`/`name`/`require_running` is produced in Task 1 and consumed identically in Task 2 and the tests. `check_resource(resource, resource_group, run) -> (state, detail)` matches across Task 1, Task 2's loop, and the tests. `verify(tool, prefix, env, resource_group, run, timeout, sleep, interval)` matches Task 2's definition and Task 3's call (which passes `timeout=` only, relying on the defaults). The `run` seam signature matches `runner.run(cmd, check, capture)` used by `rotate.py`/`backend.py`.

**Note on live validation:** the `az` verbs and the exact `provisioningState`/`runningState` values are only exercised on a real deploy; the engine tests drive the `run` seam with fakes, consistent with the rest of the Azure-touching code. Expect the first live run to be where the state strings are confirmed.
