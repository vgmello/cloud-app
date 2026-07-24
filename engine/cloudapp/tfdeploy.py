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


class DeployError(Exception):
    pass


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


def deploy(tf_dir, tfvars_file, backend_lines, tags, runner_ip, env, plan_only,
           targets=(), stack="main", run=runner.run, sleep=time.sleep):
    """init + plan (+ apply with one retry). Returns the summary line."""
    tf = ["terraform", f"-chdir={tf_dir}"]

    def terraform(args, capture=False, check=True):
        """Run terraform, surfacing captured output on failure as a DeployError."""
        try:
            return run(tf + args, capture=capture, check=check)
        except subprocess.CalledProcessError as exc:
            for stream in (exc.stdout, exc.stderr):
                if stream:
                    print(stream)
            raise DeployError(f"terraform {args[0]} failed for environment '{env}'") from exc

    terraform(["init", "-input=false"] + [f"-backend-config={line}" for line in backend_lines])

    args = ["-input=false", f"-var-file={Path(tfvars_file).resolve()}"]
    # image_tags / runner_ip are main-stack variables; the bootstrap module
    # takes only its -var-file, so never pass them there.
    if stack == "main":
        args += ["-var", f"image_tags={json.dumps(tags, separators=(',', ':'))}"]
        if runner_ip:
            args += ["-var", f"runner_ip={runner_ip}"]
    for target in targets:
        args.append(f"-target={target}")

    def plan():
        result = terraform(["plan"] + args + [f"-out={PLAN_FILE}"], capture=True)
        print("\n".join(result.stdout.splitlines()[-20:]))

    plan()
    show = terraform(["show", "-no-color", PLAN_FILE], capture=True)
    body = "\n".join(show.stdout.splitlines()[:200])
    gha.append_summary(
        f"<details><summary>terraform plan ({env})</summary>\n\n```\n{body}\n```\n</details>"
    )

    if plan_only:
        return f"plan only ({env})"

    apply_args = ["apply", "-input=false", PLAN_FILE]
    if run(tf + apply_args, check=False).returncode != 0:
        gha.warning("apply failed; retrying once in 30s (RBAC propagation)")
        sleep(30)
        plan()
        terraform(apply_args)
    return f"applied {env}"
