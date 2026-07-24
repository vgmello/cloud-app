import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import yaml

ENV = os.environ["TARGET_ENV"]
STACK_FILE = os.environ["STACK_FILE"]
EXPECTED_STACK_NAME = os.environ["EXPECTED_STACK_NAME"]
CALLER_REPO = os.environ["CALLER_REPO"]

# All four inputs are caller-controlled (they flow from the dispatch). Validate
# them BEFORE building any path, so a hostile value (e.g. `../` traversal or a
# newline) can never be interpolated into a file read, registry write, or git
# command. These run on the powerful central-repo token, so this is the gate.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")  # env / stack name: kebab, no separators
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _fail(msg):
    print(f"::error::{msg}")
    sys.exit(1)


if not _NAME_RE.match(ENV):
    _fail(f"invalid environment name '{ENV}'")
if not _NAME_RE.match(EXPECTED_STACK_NAME):
    _fail(f"invalid stack name '{EXPECTED_STACK_NAME}'")
if not _REPO_RE.match(CALLER_REPO):
    _fail(f"invalid caller repo '{CALLER_REPO}'")

# The manifest path must resolve to a file inside the caller workspace.
_caller_root = os.path.realpath("caller-workspace")
stack_path = os.path.realpath(os.path.join(_caller_root, STACK_FILE))
if os.path.isabs(STACK_FILE) or (stack_path != _caller_root and not stack_path.startswith(_caller_root + os.sep)):
    _fail(f"stack file '{STACK_FILE}' escapes the caller workspace")

registry_dir = f"central-workspace/registries/{ENV}"
registry_path = f"{registry_dir}/{EXPECTED_STACK_NAME}.yml"


def git(*args):
    """Run a git command inside the central workspace, failing hard on error."""
    subprocess.run(["git", *args], cwd="central-workspace", check=True)


# --- STEP 1: Validate Stack File and Name Property ---
if not os.path.exists(stack_path):
    print(f"::error::Stack file '{STACK_FILE}' not found inside repository '{CALLER_REPO}'!")
    sys.exit(1)

with open(stack_path) as f:
    stack_content = yaml.safe_load(f) or {}

actual_stack_name = stack_content.get("name")
if not actual_stack_name:
    print(f"::warning::No 'name' property declared in '{STACK_FILE}'. Using input name '{EXPECTED_STACK_NAME}'.")
    actual_stack_name = EXPECTED_STACK_NAME

if actual_stack_name != EXPECTED_STACK_NAME:
    print(f"::error::MISMATCH DETECTED! Workflow passed stack_name='{EXPECTED_STACK_NAME}', but file '{STACK_FILE}' declares name='{actual_stack_name}'.")
    sys.exit(1)

print(f"Stack file '{STACK_FILE}' verified (name: '{actual_stack_name}').")

# --- STEP 2: Validate Lock Ownership ---
os.makedirs(registry_dir, exist_ok=True)

if os.path.exists(registry_path):
    print(f"Lock file found for stack '{EXPECTED_STACK_NAME}'. Validating repository authorization...")
    with open(registry_path) as f:
        lock_data = yaml.safe_load(f) or {}

    allowed = lock_data.get("allowed_repos") or []

    if CALLER_REPO not in allowed:
        print(f"::error::SECURITY VIOLATION! Repository '{CALLER_REPO}' is NOT authorized to deploy stack '{EXPECTED_STACK_NAME}' in '{ENV}'.")
        print(f"Authorized Repositories: {allowed}")
        sys.exit(1)

    print(f"Repository '{CALLER_REPO}' authorized for stack '{EXPECTED_STACK_NAME}'.")

else:
    print(f"New stack detected. Registering lock for '{EXPECTED_STACK_NAME}' to '{CALLER_REPO}'...")
    new_lock = {
        "stack_name": EXPECTED_STACK_NAME,
        "environment": ENV,
        "allowed_repos": [CALLER_REPO],
        "registered_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
    }
    with open(registry_path, "w") as f:
        yaml.dump(new_lock, f, default_flow_style=False)

    # Commit and push the lock back to the central repo. Fail closed: if any git
    # step fails (e.g. a push race), the lock was not persisted, so we must not
    # let the deploy proceed with an unregistered stack. subprocess arg-lists
    # avoid shell interpolation of the caller-controlled stack name / repo.
    try:
        git("config", "user.name", "github-actions[bot]")
        git("config", "user.email", "github-actions[bot]@users.noreply.github.com")
        git("add", f"registries/{ENV}/{EXPECTED_STACK_NAME}.yml")
        git("commit", "-m", f"lock(registry): auto-register {EXPECTED_STACK_NAME} to {CALLER_REPO} [{ENV}]")
        git("pull", "--rebase", "origin", "main")
        git("push", "origin", "main")
    except subprocess.CalledProcessError as exc:
        print(f"::error::Failed to persist stack lock for '{EXPECTED_STACK_NAME}' ({exc}); aborting so ownership is not silently lost.")
        sys.exit(1)

    print(f"Stack lock created successfully at '{registry_path}'.")
