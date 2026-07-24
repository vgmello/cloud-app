"""Command-line entrypoints used by the composite actions."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import (
    backend,
    builds,
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
)
from .yamlcompat import load_yaml


def _load_json(path):
    return json.loads(Path(path).read_text())


def _load_platform(path):
    return load_yaml(Path(path).read_text()) or {}


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def cmd_parse_manifest(args):
    name, environments, tools, docker = manifest.parse(args.manifest, args.app_root)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in list(out.glob("tool.*.json")) + [out / "outputs.txt"]:
        if stale.exists():
            stale.unlink()
    for env, tool in tools.items():
        _write_json(out / f"tool.{env}.json", tool)
    gha.write_outputs(
        {
            "name": name,
            "environments": json.dumps(environments, separators=(",", ":")),
            "docker": str(docker).lower(),
        },
        fallback_file=out / "outputs.txt",
    )


def cmd_resolve_config(args):
    tool = _load_json(args.tool_json)
    tfvars = resolve.resolve(tool, args.platform_file, args.environment)
    _write_json(args.out_file, tfvars)


def cmd_enumerate_builds(args):
    plan = builds.enumerate_builds(_load_json(args.tool_json), args.tool_name, args.registry, args.git_sha)
    print(json.dumps(plan, indent=2))


def cmd_docker_build(args):
    plan = builds.enumerate_builds(_load_json(args.tool_json), args.tool_name, args.registry, args.git_sha)
    dockerbuild.build_and_push(plan, args.registry, runner.run)
    gha.write_outputs({"image-tags": json.dumps(plan["tags"], separators=(",", ":"))})


def cmd_sync_secrets(args):
    tool = _load_json(args.tool_json)
    all_secrets = secrets.load_secrets(os.environ)
    outputs = secrets.sync(
        tool,
        args.keyvault_name,
        all_secrets,
        runner.run,
        require_vault=args.require_vault,
    )
    gha.write_outputs(outputs)


def cmd_state_exists(args):
    exists = backend.state_exists(args.platform_file, args.tool_name, args.environment, runner.run)
    gha.write_outputs({"exists": "true" if exists else "false"})


def cmd_rotate_images(args):
    tool = _load_json(args.tool_json)
    platform = _load_platform(args.platform_file)
    prefix = platform.get("naming_prefix") or ""
    image_tags = json.loads(args.image_tags or "{}")
    rotate.rotate(tool, prefix, args.environment, image_tags, args.resource_group, runner.run)


def cmd_terraform_deploy(args):
    tool = _load_json(args.tool_json)
    backend_lines, tags, runner_ip = tfdeploy.prepare(
        args.platform_file, tool, args.tool_name, args.environment,
        args.image_tags, args.plan_only, stack=args.stack,
    )
    summary = tfdeploy.deploy(
        args.terraform_dir, args.tfvars_file, backend_lines, tags, runner_ip,
        args.environment, args.plan_only, targets=args.targets.split(),
        stack=args.stack,
    )
    gha.write_outputs({"summary": summary})


def cmd_login_plan(args):
    phases = identity.login_plan(args.event, backend.backend_type(args.platform_file))
    print(json.dumps(phases))


def cmd_bootstrap_vars(args):
    platform = _load_platform(args.platform_file)
    for field in ("subscription_id", "location"):
        if not platform.get(field):
            raise ValueError(f"{field} missing in {args.platform_file}")
    # Azure Blob state account id, so bootstrap can grant the plan/apply
    # identities data-plane access to the tfstate container. Empty for s3.
    state = platform.get("state_backend") or {}
    state_account_id = ""
    if state.get("type") == "azurerm" and state.get("storage_account") and state.get("resource_group"):
        state_account_id = (
            f"/subscriptions/{platform['subscription_id']}"
            f"/resourceGroups/{state['resource_group']}"
            f"/providers/Microsoft.Storage/storageAccounts/{state['storage_account']}"
        )
    out = {
        "name": args.name,
        "environment": args.environment,
        "subscription_id": platform["subscription_id"],
        "location": platform["location"],
        # Optional: the shared ABAC-enabled ACR id enables the repo-scoped push
        # grant in the bootstrap stack. Empty when not configured.
        "acr_id": (platform.get("acr") or {}).get("id", ""),
        "state_account_id": state_account_id,
        "state_container": state.get("container", "") if state_account_id else "",
        "plan_subjects": identity.federation_subjects(
            "plan", args.mode, args.app_repo, args.central_repo, args.environment
        ),
        "apply_subjects": identity.federation_subjects(
            "apply", args.mode, args.app_repo, args.central_repo, args.environment
        ),
    }
    print(json.dumps(out))


def cmd_validate_lock(args):
    registry.validate_names(args.environment, args.stack_name, args.caller_repo)
    stack_path = registry.resolve_stack_path(args.caller_root, args.stack_file)

    if not os.path.exists(stack_path):
        raise registry.RegistryError(
            f"Stack file '{args.stack_file}' not found inside repository '{args.caller_repo}'!"
        )
    declared = _load_platform(stack_path).get("name")
    if not declared:
        gha.warning(f"No 'name' declared in '{args.stack_file}'. Using input name '{args.stack_name}'.")
    name = registry.reconcile_stack_name(declared, args.stack_name)
    gha.notice(f"Stack file '{args.stack_file}' verified (name: '{name}').")

    registry_dir = Path(args.central_root) / "registries" / args.environment
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry_path = registry_dir / f"{args.stack_name}.yml"

    if registry_path.exists():
        lock = _load_platform(registry_path)
        if not registry.authorize_caller(lock, args.caller_repo):
            raise registry.RegistryError(
                f"SECURITY VIOLATION! Repository '{args.caller_repo}' is NOT authorized to "
                f"deploy stack '{args.stack_name}' in '{args.environment}'. "
                f"Authorized: {lock.get('allowed_repos') or []}"
            )
        gha.notice(f"Repository '{args.caller_repo}' authorized for stack '{args.stack_name}'.")
        return

    gha.notice(f"New stack detected. Registering lock for '{args.stack_name}' to '{args.caller_repo}'.")
    registered_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lock = registry.new_lock(args.stack_name, args.environment, args.caller_repo, registered_at)
    registry_path.write_text(yaml.safe_dump(lock, default_flow_style=False))
    registry.persist_lock(runner.run, args.central_root, args.environment, args.stack_name, args.caller_repo)
    gha.notice(f"Stack lock created successfully at '{registry_path}'.")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cloudapp")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse-manifest")
    p.add_argument("--manifest", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--app-root", default=".")
    p.set_defaults(func=cmd_parse_manifest)

    p = sub.add_parser("resolve-config")
    p.add_argument("--tool-json", required=True)
    p.add_argument("--platform-file", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--out-file", required=True)
    p.set_defaults(func=cmd_resolve_config)

    p = sub.add_parser("enumerate-builds")
    p.add_argument("--tool-json", required=True)
    p.add_argument("--tool-name", required=True)
    p.add_argument("--registry", required=True)
    p.add_argument("--git-sha", required=True)
    p.set_defaults(func=cmd_enumerate_builds)

    p = sub.add_parser("docker-build")
    p.add_argument("--tool-json", required=True)
    p.add_argument("--tool-name", required=True)
    p.add_argument("--registry", required=True)
    p.add_argument("--git-sha", required=True)
    p.set_defaults(func=cmd_docker_build)

    p = sub.add_parser("sync-secrets")
    p.add_argument("--tool-json", required=True)
    p.add_argument("--keyvault-name", required=True)
    p.add_argument("--require-vault", action="store_true")
    p.set_defaults(func=cmd_sync_secrets)

    p = sub.add_parser("state-exists")
    p.add_argument("--platform-file", required=True)
    p.add_argument("--tool-name", required=True)
    p.add_argument("--environment", required=True)
    p.set_defaults(func=cmd_state_exists)

    p = sub.add_parser("rotate-images")
    p.add_argument("--tool-json", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--platform-file", required=True)
    p.add_argument("--image-tags", default="{}")
    p.add_argument("--resource-group", required=True)
    p.set_defaults(func=cmd_rotate_images)

    p = sub.add_parser("terraform-deploy")
    p.add_argument("--terraform-dir", required=True)
    p.add_argument("--tfvars-file", required=True)
    p.add_argument("--tool-json", required=True)
    p.add_argument("--tool-name", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--platform-file", required=True)
    p.add_argument("--image-tags", default="{}")
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--targets", default="")
    p.add_argument("--stack", default="main", choices=["main", "bootstrap"])
    p.set_defaults(func=cmd_terraform_deploy)

    p = sub.add_parser("login-plan")
    p.add_argument("--event", required=True)
    p.add_argument("--platform-file", required=True)
    p.set_defaults(func=cmd_login_plan)

    p = sub.add_parser("bootstrap-vars")
    p.add_argument("--name", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--app-repo", required=True)
    p.add_argument("--central-repo", required=True)
    p.add_argument("--platform-file", required=True)
    p.set_defaults(func=cmd_bootstrap_vars)

    p = sub.add_parser("validate-lock")
    p.add_argument("--environment", required=True)
    p.add_argument("--stack-file", required=True)
    p.add_argument("--stack-name", required=True)
    p.add_argument("--caller-repo", required=True)
    p.add_argument("--caller-root", default="caller-workspace")
    p.add_argument("--central-root", default="central-workspace")
    p.set_defaults(func=cmd_validate_lock)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (manifest.ManifestError, resolve.ResolveError, secrets.SyncError,
            tfdeploy.DeployError, backend.BackendError, rotate.RotateError,
            registry.RegistryError, ValueError) as exc:
        gha.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
