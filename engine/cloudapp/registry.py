"""Stack-lock registry: the authorization gate for the deploy control repo.

Trust-on-first-use ownership of stack names per environment. The first caller
repo to deploy a stack name claims it; later callers must appear in the lock's
``allowed_repos``. These checks run on the privileged central-repo token, so
every caller-controlled input is validated before it touches a path, a registry
file, or a git command. The pure helpers here are unit-tested; only the CLI
command wires them to the filesystem and git.
"""

import os
import re
import subprocess

# env / stack name: kebab, no separators; caller repo: owner/name.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

# manifest path inside the caller workspace: no shell metacharacters, no
# absolute paths, no traversal. The gate does not rely on quoting discipline
# at downstream call sites.
STACK_FILE_RE = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")


class RegistryError(Exception):
    pass


def validate_names(env, stack_name, caller_repo, stack_file):
    """Reject any caller-controlled identifier that could escape a path or a
    git command before it is ever interpolated. Runs first — it is the gate."""
    if not NAME_RE.fullmatch(env):
        raise RegistryError(f"invalid environment name '{env}'")
    if not NAME_RE.fullmatch(stack_name):
        raise RegistryError(f"invalid stack name '{stack_name}'")
    if not REPO_RE.fullmatch(caller_repo):
        raise RegistryError(f"invalid caller repo '{caller_repo}'")
    if not STACK_FILE_RE.fullmatch(stack_file or ""):
        raise RegistryError(f"invalid stack file '{stack_file}'")
    if stack_file.startswith("/") or ".." in stack_file.split("/"):
        raise RegistryError(f"invalid stack file '{stack_file}'")


def resolve_stack_path(caller_root, stack_file):
    """Absolute path of ``stack_file`` inside ``caller_root``. Raises if the
    manifest path is absolute or escapes the workspace (via ``..`` or a
    symlink) — realpath collapses both before the containment check."""
    root = os.path.realpath(caller_root)
    path = os.path.realpath(os.path.join(root, stack_file))
    if os.path.isabs(stack_file) or (path != root and not path.startswith(root + os.sep)):
        raise RegistryError(f"stack file '{stack_file}' escapes the caller workspace")
    return path


def reconcile_stack_name(declared, expected):
    """The stack name to use. A manifest that declares a different name than
    the dispatched one is a mismatch and fails closed; a manifest with no name
    falls back to the dispatched name (the caller should warn)."""
    if declared and declared != expected:
        raise RegistryError(
            f"MISMATCH DETECTED! Workflow passed stack_name='{expected}', "
            f"but the manifest declares name='{declared}'."
        )
    return declared or expected


def authorize_caller(lock_data, caller_repo):
    """True if ``caller_repo`` owns (is allow-listed for) the locked stack."""
    allowed = (lock_data or {}).get("allowed_repos") or []
    return caller_repo in allowed


def new_lock(stack_name, env, caller_repo, registered_at):
    """The lock payload registered on first use of a stack name."""
    return {
        "stack_name": stack_name,
        "environment": env,
        "allowed_repos": [caller_repo],
        "registered_at": registered_at,
    }


def persist_lock(runner, cwd, env, stack_name, caller_repo):
    """Commit and push the new lock back to the central repo. Fail-closed: if
    any git step fails (e.g. a push race), the lock was not persisted, so we
    raise instead of letting the deploy proceed with an unregistered stack.
    Arg-lists (never a shell string) keep the caller-controlled name/repo from
    being interpolated into a command."""
    def git(*args):
        runner(["git", *args], cwd=cwd)

    try:
        git("config", "user.name", "github-actions[bot]")
        git("config", "user.email", "github-actions[bot]@users.noreply.github.com")
        git("add", f"registries/{env}/{stack_name}.yml")
        git("commit", "-m", f"lock(registry): auto-register {stack_name} to {caller_repo} [{env}]")
        git("pull", "--rebase", "origin", "main")
        git("push", "origin", "main")
    except subprocess.CalledProcessError as exc:
        raise RegistryError(
            f"Failed to persist stack lock for '{stack_name}' ({exc}); "
            "aborting so ownership is not silently lost."
        )
