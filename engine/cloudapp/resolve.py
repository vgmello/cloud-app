"""Merge a per-environment tool config with platform config into tfvars."""

from pathlib import Path

from .yamlcompat import load_yaml


class ResolveError(Exception):
    pass


def resolve(tool, platform_path, env_name):
    platform_path = Path(platform_path)
    if not platform_path.is_file():
        raise ResolveError(
            f"platform config not found: {platform_path} "
            f"(environment '{env_name}' has no platform config file)"
        )
    platform = load_yaml(platform_path.read_text())
    # `deploy:` governs how the action ships the stack, not what Terraform
    # builds. Dropping it here keeps it out of tfvars entirely, so the module
    # never sees a key it has no use for and the generated test fixtures stay
    # unchanged when a caller sets a deploy policy.
    config = {k: v for k, v in tool.items() if k != "deploy"}
    return {"config": {**config, "environment": env_name, "platform": platform}}
