"""Terraform init/plan/apply for one environment, with the platform conventions:
per-tool state key, plan-only placeholder tags, runner-IP allowlisting, and a
single retry for RBAC propagation."""

import json
import subprocess
import time
from pathlib import Path

from . import backend, builds, gha, runner
from .yamlcompat import load_yaml

PLAN_FILE = "tfplan"
INPUT_FALSE = "-input=false"

# Substrings that mark a transient authorization failure — a fresh RBAC grant
# that has not propagated yet. Only these are worth the retry; quota, policy,
# and configuration errors are terminal and must surface immediately.
_TRANSIENT_APPLY_ERRORS = (
    "authorizationfailed",
    "does not have authorization",
    "authorizationpermissionmismatch",
    "linkedauthorizationfailed",
)


class DeployError(Exception):
    pass


def _is_transient_authz(text):
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _TRANSIENT_APPLY_ERRORS)


def prepare(platform_path, tool, tool_name, env, image_tags_json, plan_only,
            stack="main", fetch_ip=runner.fetch_runner_ip):
    """Resolve backend config lines, image tags, and runner IP for a deploy."""
    backend_lines = backend.render(platform_path, tool_name, env, stack=stack)
    tags = json.loads(image_tags_json or "{}")
    platform = load_yaml(Path(platform_path).read_text()) or {}
    if plan_only and not tags:
        registry = (platform.get("acr") or {}).get("login_server", "acr.invalid")
        tags = builds.enumerate_builds(tool, tool_name, registry, "plan-placeholder")["tags"]
    # Runner allowlisting applies only to the main stack; the bootstrap module
    # declares no runner_ip variable.
    runner_ip = None
    if stack == "main" and platform.get("runner_access") == "public-allowlist":
        runner_ip = fetch_ip()
    return backend_lines, tags, runner_ip


def _terraform(run, tf, args, env, capture=False, check=True):
    """Run terraform, surfacing captured output on failure as a DeployError."""
    try:
        return run(tf + args, capture=capture, check=check)
    except subprocess.CalledProcessError as exc:
        for stream in (exc.stdout, exc.stderr):
            if stream:
                print(stream)
        raise DeployError(f"terraform {args[0]} failed for environment '{env}'") from exc


def _plan_args(tfvars_file, tags, runner_ip, stack, targets):
    """Plan/apply variable args. image_tags / runner_ip are main-stack
    variables; the bootstrap module takes only its -var-file, so never pass
    them there."""
    args = [INPUT_FALSE, f"-var-file={Path(tfvars_file).resolve()}"]
    if stack == "main":
        args += ["-var", f"image_tags={json.dumps(tags, separators=(',', ':'))}"]
        if runner_ip:
            args += ["-var", f"runner_ip={runner_ip}"]
    args += [f"-target={target}" for target in targets]
    return args


def _plan(run, tf, args, env):
    result = _terraform(run, tf, ["plan"] + args + [f"-out={PLAN_FILE}"], env, capture=True)
    print("\n".join(result.stdout.splitlines()[-20:]))


def _apply_with_retry(run, tf, env, replan, sleep):
    """Apply the saved plan; on a transient authz error, re-plan and apply once
    more after RBAC propagation. Non-transient failures surface immediately."""
    apply_args = ["apply", INPUT_FALSE, PLAN_FILE]
    result = run(tf + apply_args, capture=True, check=False)
    if result.returncode == 0:
        return
    output = (result.stdout or "") + (result.stderr or "")
    if not _is_transient_authz(output):
        print(output)
        raise DeployError(f"terraform apply failed for environment '{env}'")
    gha.warning("apply hit a transient authorization error; retrying once in 30s (RBAC propagation)")
    sleep(30)
    replan()
    _terraform(run, tf, apply_args, env)  # surfaces output and raises DeployError if it fails again


def deploy(tf_dir, tfvars_file, backend_lines, tags, runner_ip, env, plan_only,
           targets=(), stack="main", run=runner.run, sleep=time.sleep):
    """init + plan (+ apply with one retry). Returns the summary line."""
    tf = ["terraform", f"-chdir={tf_dir}"]

    _terraform(run, tf, ["init", INPUT_FALSE] + [f"-backend-config={line}" for line in backend_lines], env)

    args = _plan_args(tfvars_file, tags, runner_ip, stack, targets)

    def replan():
        _plan(run, tf, args, env)

    replan()
    show = _terraform(run, tf, ["show", "-no-color", PLAN_FILE], env, capture=True)
    body = "\n".join(show.stdout.splitlines()[:200])
    gha.append_summary(
        f"<details><summary>terraform plan ({env})</summary>\n\n```\n{body}\n```\n</details>"
    )

    if plan_only:
        return f"plan only ({env})"

    _apply_with_retry(run, tf, env, replan, sleep)
    return f"applied {env}"
