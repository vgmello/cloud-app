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


_COMPONENT_RE = re.compile(r"[a-z][a-z0-9-]{0,29}")


def state_key(name, env, stack="main", component=None):
    """Blob path of one stack's Terraform state.

    A stack that no manifest splits keeps the historical
    ``<name>/<env>.tfstate`` key, so adopting components never migrates an
    existing deploy. A manifest that declares ``component: x`` gets its own
    state at ``<name>/components/x/<env>.tfstate``: same stack, same resource
    group, same Key Vault, but a state file that only describes the resources
    that component owns. That separation is the whole point — one repo can
    create the database and another the app, deploying at different times,
    without either apply seeing the other's resources as orphans to destroy.

    The bootstrap stack is per-stack, not per-component (one resource group and
    one pair of plan/apply identities serve every component), so its key
    ignores ``component``.
    """
    suffix = "bootstrap.tfstate" if stack == "bootstrap" else "tfstate"
    if stack == "bootstrap" or not component:
        return f"{name}/{env}.{suffix}"
    if not _COMPONENT_RE.fullmatch(component):
        raise BackendError(
            f"component '{component}' must start with a lowercase letter and contain only "
            "lowercase alphanumerics and hyphens (max 30 characters)"
        )
    return f"{name}/components/{component}/{env}.{suffix}"


_ENV_ALNUM = re.compile(r"[a-z0-9]+")
_CONTAINER_FRAGMENT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_CONTAINER = 63
MIN_CONTAINER = 3


def stack_container(sb, name, env, stack="main"):
    """Blob container holding one stack's Terraform state.

    The bootstrap stack keeps its state in the shared platform container: a
    single per-environment control-plane identity owns every bootstrap state,
    callers never hold it, and Terraform cannot init into a container the same
    run has not created yet. The main stack gets its own container so the
    plan/apply grants can be scoped to it instead of to every stack's state.

    Components of one stack share this container; only their state *key*
    differs (see state_key). That is deliberate: every component deploys under
    the same RG-scoped plan/apply identities, bootstrapped once for the stack
    and federated to the same ``allowed_repos``, so they are already one trust
    domain and one blob grant covers them all. The boundary components give you
    is over Terraform's view of what exists, not over who may read the state.

    The main-stack container name is built by joining ``<name>-<env>``. That
    join is guaranteed unambiguous -- distinct (name, env) pairs can never
    collide onto the same container and reunite their Terraform state --
    because env is required to be non-empty lowercase alphanumeric with no
    hyphen, and name is required to be a valid "container fragment": lowercase
    alphanumeric with single internal hyphens and no leading, trailing, or
    consecutive hyphens. Since env never contains a hyphen, the final hyphen
    in the joined string is always the separator between name and env, so
    splitting there is unique and the (name, env) pair can be recovered from
    the container name. Values that would violate either constraint are
    rejected outright rather than normalized, because normalizing them (e.g.
    stripping a trailing hyphen or collapsing consecutive hyphens) would make
    two distinct inputs produce the same container.
    """
    if stack == "bootstrap":
        return sb["container"]
    if not _ENV_ALNUM.fullmatch(env):
        raise BackendError(
            f"environment '{env}' must be non-empty lowercase alphanumeric; a hyphen or "
            "other separator would make the '<name>-<env>' state container name ambiguous"
        )
    if not _CONTAINER_FRAGMENT.fullmatch(name):
        raise BackendError(
            f"stack name '{name}' must be lowercase alphanumeric with single internal "
            "hyphens (no leading, trailing, or consecutive hyphens)"
        )
    candidate = f"{name}-{env}"
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


def state_exists(platform_path, name, env, run, stack="main", component=None):
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
         "--name", state_key(name, env, stack, component),
         "--auth-mode", "login",
         "--query", "exists", "-o", "tsv"],
        check=False, capture=True,
    )
    return result.returncode == 0 and (result.stdout or "").strip().lower() == "true"


def render(platform_path, name, env, stack="main", component=None):
    """-backend-config key=value lines for one tool + environment + stack."""
    sb = _config(platform_path)
    key = state_key(name, env, stack, component)
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
