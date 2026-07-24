"""Terraform backend configuration (azurerm or s3) from platform config."""

from pathlib import Path

from .yamlcompat import load_yaml


class BackendError(Exception):
    pass


def _config(platform_path):
    platform = load_yaml(Path(platform_path).read_text()) or {}
    sb = platform.get("state_backend")
    if not sb or not sb.get("type"):
        raise BackendError(f"state_backend.type missing in {platform_path}")
    return sb


def backend_type(platform_path):
    return _config(platform_path)["type"]


def state_key(name, env, stack="main"):
    suffix = "bootstrap.tfstate" if stack == "bootstrap" else "tfstate"
    return f"{name}/{env}.{suffix}"


def state_exists(platform_path, name, env, run, stack="main"):
    """True if the Terraform state blob for this tool+env already exists.

    A cheap first-deploy signal (one az call, no terraform init) evaluated under
    the already-logged-in deploy identity. Only azurerm backends are probed; any
    other backend type returns False, and an az failure returns False, so the
    caller treats the deploy as first/undetermined and never wrongly skips an
    apply.
    """
    sb = _config(platform_path)
    if sb["type"] != "azurerm":
        return False
    for field in ("storage_account", "container"):
        if not sb.get(field):
            raise BackendError(f"state_backend.{field} missing in {platform_path}")
    result = run(
        ["az", "storage", "blob", "exists",
         "--account-name", sb["storage_account"],
         "--container-name", sb["container"],
         "--name", state_key(name, env, stack),
         "--auth-mode", "login",
         "--query", "exists", "-o", "tsv"],
        check=False, capture=True,
    )
    return result.returncode == 0 and (result.stdout or "").strip().lower() == "true"


def render(platform_path, name, env, stack="main"):
    """-backend-config key=value lines for one tool + environment + stack."""
    sb = _config(platform_path)
    key = state_key(name, env, stack)
    if sb["type"] == "azurerm":
        for field in ("resource_group", "storage_account", "container"):
            if not sb.get(field):
                raise BackendError(f"state_backend.{field} missing in {platform_path}")
        return [
            f"resource_group_name={sb['resource_group']}",
            f"storage_account_name={sb['storage_account']}",
            f"container_name={sb['container']}",
            f"key={key}",
            "use_oidc=true",
            "use_azuread_auth=true",
        ]
    if sb["type"] == "s3":
        for field in ("bucket", "region", "role_arn"):
            if not sb.get(field):
                raise BackendError(f"state_backend.{field} missing in {platform_path}")
        lines = [
            f"bucket={sb['bucket']}",
            f"key={key}",
            f"region={sb['region']}",
        ]
        if sb.get("dynamodb_table"):
            lines.append(f"dynamodb_table={sb['dynamodb_table']}")
        lines += [f"role_arn={sb['role_arn']}", "encrypt=true"]
        return lines
    raise BackendError(f"unknown state backend type '{sb['type']}' in {platform_path}")
