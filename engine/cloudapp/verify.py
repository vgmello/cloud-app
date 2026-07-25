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
