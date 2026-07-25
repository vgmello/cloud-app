"""Terraform backend configuration (azurerm or s3) from platform config."""

import re
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


_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_ENV_ALNUM = re.compile(r"[a-zA-Z0-9]*")
MAX_CONTAINER = 63
MIN_CONTAINER = 3


def stack_container(sb, name, env, stack="main"):
    """Blob container holding one stack's Terraform state.

    The bootstrap stack keeps its state in the shared platform container: a
    single per-environment control-plane identity owns every bootstrap state,
    callers never hold it, and Terraform cannot init into a container the same
    run has not created yet. The main stack gets its own container so the
    plan/apply grants can be scoped to it instead of to every stack's state.

    The main-stack container name is built by joining ``<name>-<env>``. That
    join is only unambiguous -- guaranteeing two distinct (name, env) pairs
    can never collide onto the same container and reunite their Terraform
    state -- if env is purely alphanumeric. A hyphen (or any other separator)
    in env would let, e.g., ("orders-api-east", "dev") and ("orders-api",
    "east-dev") both produce "orders-api-east-dev". The manifest schema
    already constrains environment keys to be hyphen-free, but that
    constraint lives three layers away; it is re-asserted here so the
    collision-freedom guarantee does not silently depend on it.
    """
    if stack == "bootstrap":
        return sb["container"]
    if not _ENV_ALNUM.fullmatch(env):
        raise BackendError(
            f"environment '{env}' must be alphanumeric; a hyphen or other "
            "separator would make the '<name>-<env>' state container name ambiguous"
        )
    candidate = _NON_ALNUM.sub("-", f"{name}-{env}".lower()).strip("-")
    if len(candidate) > MAX_CONTAINER:
        raise BackendError(
            f"state container name '{candidate}' exceeds {MAX_CONTAINER} characters; "
            "shorten the stack name or the environment name"
        )
    if len(candidate) < MIN_CONTAINER:
        raise BackendError(
            f"state container name '{candidate}' is shorter than {MIN_CONTAINER} characters; "
            "azure storage requires container names of at least 3 characters"
        )
    return candidate


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
         "--container-name", stack_container(sb, name, env, stack),
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
            f"container_name={stack_container(sb, name, env, stack)}",
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
