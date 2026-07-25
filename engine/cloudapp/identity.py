"""Deploy identity model: federation subjects and login sequencing.

Pure functions — the security-critical mapping from (event, mode) to which
managed identity signs in for which phase, and to the OIDC subject each
identity's federated credential must trust.
"""

import re

MODES = ("self", "delegated")
DEPLOY_IDENTITIES = ("plan", "apply")
EVENTS = ("pull_request", "default_branch")

# OIDC subjects are built by string interpolation; these components must not be
# able to inject subject-claim delimiters (`:`) or wildcards.
_ENV_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,15}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _validate(app_repo, central_repo, env):
    if not _ENV_RE.fullmatch(env):
        raise ValueError(f"invalid environment name '{env}'")
    for repo in (app_repo, central_repo):
        if not _REPO_RE.fullmatch(repo):
            raise ValueError(f"invalid repo '{repo}'")


def federation_subjects(mi, mode, app_repo, central_repo, env):
    """OIDC subjects a per-tool MI's federated credentials must trust."""
    if mode not in MODES:
        raise ValueError(f"unknown mode '{mode}'")
    if mi not in DEPLOY_IDENTITIES:
        raise ValueError(f"unknown deploy identity '{mi}'")
    _validate(app_repo, central_repo, env)

    # Split topology: the caller runs the resource deploy under the RG-scoped
    # plan/apply identities, so both modes federate plan/apply to the app
    # (caller) repo. Only the bootstrap identity (minted in the control repo, and
    # not one of DEPLOY_IDENTITIES) is federated to the control repo. central_repo
    # is retained for validation/compatibility but no longer appears in a subject.
    if mi == "plan":
        return [f"repo:{app_repo}:pull_request", f"repo:{app_repo}:environment:{env}"]
    return [f"repo:{app_repo}:environment:{env}"]


def login_plan(event, backend_type):
    """Ordered deploy phases for an event. Each phase names the identity that
    signs in, the terraform action, the stack, and whether the state backend
    needs its own (AWS) OIDC login this phase."""
    if event not in EVENTS:
        raise ValueError(f"unknown event '{event}'")
    state_login = backend_type == "s3"

    if event == "pull_request":
        phases = [{"identity": "plan", "action": "plan", "stack": "main"}]
    else:
        phases = [
            {"identity": "bootstrap", "action": "apply", "stack": "bootstrap"},
            {"identity": "plan", "action": "plan", "stack": "main"},
            {"identity": "apply", "action": "apply", "stack": "main"},
        ]
    for p in phases:
        p["state_login"] = state_login
    return phases
