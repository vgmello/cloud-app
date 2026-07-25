"""Post-deploy verification: do the manifest's resources exist and are they healthy?

Checks reality rather than a derived signal. Runs after both deploy lanes — the
Terraform apply and the direct image rotation — and even when neither changed
anything, which is what makes a half-built stack loud instead of silently green.
"""

import json
import re
import time

from . import naming

NOT_FOUND = re.compile(
    r"ResourceNotFound|was not found|could not be found|does not exist|NotFound",
    re.IGNORECASE,
)

HEALTHY = "healthy"
PENDING = "pending"
FAILED = "failed"

POLL_INTERVAL = 10

# runningState is an extensible enum: assert against the states we know are bad
# rather than requiring an exact "Running", so new/healthy service states
# (e.g. RunningAtMaxScale) do not fail a good deploy.
RUNNING_TERMINAL = {"Failed"}
RUNNING_PENDING = {"Processing", "Stopped", "Activating", "Deactivating", "Unknown", "Degraded"}

# provisioningState values that mean the resource is gone/going away, not just
# still converging — polling to timeout on these would only waste the budget.
PROVISIONING_TERMINAL = {"Failed", "Deprovisioning", "Deprovisioned"}


class VerifyError(Exception):
    pass


def expected_resources(tool, prefix, env):
    """Every resource the manifest declares that can be health-checked.

    Static sites are excluded: no revisions and no image. A container app only
    has to be *running* when it declares at least one replica — a scale-to-zero
    app is legitimately idle and must not fail the check. A missing replicas
    key defaults to requiring a running revision (manifest.REPLICA_DEFAULTS min=1),
    ensuring the check fails closed — only an explicit min: 0 may be idle.
    """
    resources = []
    for app_key, app in (tool.get("apps") or {}).items():
        replicas = app.get("replicas") or {}
        # A missing replicas/min means always-on (manifest.REPLICA_DEFAULTS), so
        # default to requiring a running revision — the check must fail closed.
        # Only an explicit min: 0 (scale-to-zero) may be idle.
        min_replicas = replicas.get("min")
        if min_replicas is None:
            min_replicas = 1
        resources.append({
            "kind": "containerapp",
            "name": naming.container_app_name(tool, prefix, env, app_key),
            "require_running": min_replicas > 0,
        })
    for func_key in (tool.get("functions") or {}):
        resources.append({
            "kind": "functionapp",
            "name": naming.function_app_name(tool, prefix, env, func_key),
            "require_running": True,
        })
    return resources


def _az(run, cmd, resource_group):
    """Run an az query; classify a failure as terminal (not-found) or transient."""
    result = run(cmd, check=False, capture=True)
    if result.returncode == 0:
        return None, (result.stdout or "").strip()
    stderr = result.stderr or ""
    if NOT_FOUND.search(stderr):
        return FAILED, (
            f"not found in {resource_group} — the stack is incomplete; re-run with "
            f"always_run_terraform: true to finish it ({stderr.strip()[:200]})"
        )
    return PENDING, f"az query failed: {stderr.strip()[:200]}"


def _check_container_app(resource, resource_group, run):
    state, out = _az(run, [
        "az", "containerapp", "show",
        "--name", resource["name"], "--resource-group", resource_group,
        "--query", "properties.latestRevisionName", "-o", "tsv",
    ], resource_group)
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
    ], resource_group)
    if state:
        return state, out
    try:
        states = json.loads(out or "{}")
    except ValueError:
        return PENDING, f"unparseable revision state for {revision}"

    prov = states.get("prov") or "unknown"
    running = states.get("running") or "unknown"
    detail = f"revision {revision} provisioningState={prov} runningState={running}"
    if prov in PROVISIONING_TERMINAL or running in RUNNING_TERMINAL:
        return FAILED, detail
    if prov != "Provisioned":
        return PENDING, detail
    if resource["require_running"] and running in RUNNING_PENDING:
        return PENDING, detail
    return HEALTHY, detail


def _check_function_app(resource, resource_group, run):
    state, out = _az(run, [
        "az", "functionapp", "show",
        "--name", resource["name"], "--resource-group", resource_group,
        "--query", "state", "-o", "tsv",
    ], resource_group)
    if state:
        return state, out
    if not out:
        # az functionapp show can exit 0 with empty output for a nonexistent
        # site — an existing site always reports a state, so treat this as
        # not-found rather than letting it poll to timeout.
        return FAILED, (
            f"not found in {resource_group} — the stack is incomplete; re-run with "
            "always_run_terraform: true to finish it (empty az functionapp show output)"
        )
    detail = f"state={out}"
    return (HEALTHY, detail) if out == "Running" else (PENDING, detail)


def check_resource(resource, resource_group, run):
    """One probe of one resource. Returns (state, human-readable detail)."""
    if resource["kind"] == "containerapp":
        return _check_container_app(resource, resource_group, run)
    return _check_function_app(resource, resource_group, run)


def verify(tool, prefix, env, resource_group, run, timeout=300, sleep=time.sleep,
           interval=POLL_INTERVAL, now=time.monotonic):
    """Poll every declared resource until all are healthy or the deadline passes.

    Raises VerifyError as soon as any resource reaches a terminal state, so a
    genuinely broken deploy fails fast instead of waiting out the timeout.

    Polls against a wall-clock deadline (start + timeout) rather than a fixed
    attempt count: each round costs len(pending) resources worth of `az`
    invocations plus the sleep, so a fixed attempt count can overshoot the
    configured budget several times over on a multi-resource stack.
    """
    resources = expected_resources(tool, prefix, env)
    if not resources:
        print("no verifiable resources declared")
        return 0

    start = now()
    deadline = start + timeout
    pending = list(resources)
    details = {}
    while True:
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
        if now() >= deadline:
            break
        sleep(min(interval, deadline - now()))

    elapsed = int(now() - start)
    unhealthy = ", ".join(f"{r['name']} [{details.get(r['name'], 'unknown')}]" for r in pending)
    raise VerifyError(
        f"not healthy after {elapsed}s: {unhealthy}. "
        "Check the container logs; if the stack is incomplete, re-run with "
        "always_run_terraform: true."
    )
