# CI provider adapter: GitHub Actions and GitLab CI

Design for running cloud-app on either GitHub Actions or GitLab CI from a single
source tree, without changing the manifest.

## Goal

An organization adopting cloud-app picks **one** CI host. The platform must work
on either. The `.cloud-app.yml` manifest is identical on both — a stack manifest
written for a GitHub org deploys unchanged on a GitLab org.

## Non-goals

- **Cross-host federation.** Only one control plane exists at a time. A GitLab
  app project never dispatches to a GitHub control repo. This removes the
  namespace-collision, registry-sync, and cross-host-token problems entirely.
- **Manifest changes.** No new fields, no provider discriminator, no conditional
  schema. The manifest describes an application, not a CI system.
- **Changing the deploy model.** The split topology on `main` (Phase 1 mints
  identities in the control plane, Phase 2 deploys on the caller's runner) is
  preserved as-is.

## The boundary

The reframe that drives this design: **`terraform/azure` is not the product.**
It is a reference implementation showing how a team can consume the abstraction.
The product is the interface.

| Ours — versioned and published                        | Consumer's — lives in the control repo                  |
| ----------------------------------------------------- | ------------------------------------------------------- |
| `cloud-app.schema.json` — the manifest interface      | `environments/*.yml` — landing-zone description         |
| `engine/` — parse, merge, validate, resolve to tfvars | `terraform/` — their modules, seeded from our reference |
| the tfvars contract (below)                           | `registries/` — stack locks and bootstrap cache         |
| CI drivers (GitHub actions, GitLab components)        | the bootstrap pipeline                                  |
| the runtime image                                     |                                                         |

The contract between the two halves is the tfvars document the engine emits:

```json
{ "config": { "…manifest fields", "environment": "prod", "platform": {…}, "names": {…} } }
```

Anything that consumes that document is the consumer's business.

## Repo topology

The monorepo stays the single source of truth. Release publishes filtered trees.

```
cloud-app/                     (monorepo, source of truth)
  engine/                      ours; tests stripped on publish
    cloudapp/
      schema/cloud-app.schema.json   <- relocated, see below
      ci/                            <- new adapter package
  ci/github/                   composite actions + workflows
  ci/gitlab/                   CI components
  runtime/Dockerfile           the runtime image
  control-template/            becomes the control repo users clone
  reference/terraform/azure/   the reference module, seeds control-template
  docs/ site/ samples/         never published
```

Published on release:

| Repo / artifact     | Holds                                                                      | Consumed as                                               |
| ------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------- |
| `cloud-app-github`  | composite actions, workflows                                               | `uses: org/cloud-app-github/.github/actions/cloud-app@v1` |
| `cloud-app-gitlab`  | CI components (YAML only)                                                  | `include: component: …/cloud-app@v1`                      |
| `cloud-app-control` | template: `environments/`, `terraform/`, `registries/`, bootstrap pipeline | cloned once per organization                              |
| `cloud-app-runtime` | container image: engine + terraform + az + jq/yq                           | `docker run` (GitHub) / `image:` (GitLab)                 |

Naming above is a recommendation, not a constraint; it drops `-actions` because
GitLab's unit is a component and because the GitHub repo is a driver, not a
library.

### Version coupling

Today `cloud-app/action.yml:213` sets the bootstrap dispatch ref from
`github.action_ref`, which works only because the action repo and the control
repo are the same repo. After the split the control repo is consumer-owned with
its own refs, so that implicit coupling is gone.

Replacement: the CI drivers and the runtime image are versioned together and
pinned by the caller (`@v1` selects both). The control repo is pinned
independently by the consumer, because its contents — landing zone and Terraform
modules — are genuinely theirs. `bootstrap.fingerprint` continues to hash the
bootstrap Terraform, which now correctly means "the consumer's bootstrap stack
changed", and the release-time guard in `release.yml:29-33` is dropped since it
no longer has a stack of ours to guard.

## Engine CI adapter

All CI coupling in the engine flows through one module today (`gha.py`, 24 call
sites: `cli.py` 18, `secrets.py` 3, `tfdeploy.py` 2, `bootcache.py` 1). It
becomes a protocol package with thin per-provider implementations.

```
engine/cloudapp/ci/
  __init__.py    detect() + late-bound dispatch + use() for tests
  base.py        file-only; no CI assumptions
  github.py      GITHUB_OUTPUT, GITHUB_STEP_SUMMARY, ::notice/warning/error::
  gitlab.py      dotenv report file, plain log lines
```

`gha.py` is deleted; the 24 call sites become `ci.`. No business-logic module
gains a provider branch, and there are no `github_*.py` / `gitlab_*.py` forks.

```python
# engine/cloudapp/ci/__init__.py
_impl = None

def detect(env=None):
    env = os.environ if env is None else env
    name = env.get("CLOUDAPP_CI") or (
        "github" if env.get("GITHUB_ACTIONS")
        else "gitlab" if env.get("GITLAB_CI")
        else "base")
    try:
        return {"base": base, "github": github, "gitlab": gitlab}[name]
    except KeyError:
        raise ValueError(f"unknown CI provider '{name}'")

def use(impl):          # tests: ci.use(fake); ci.use(None) resets
    global _impl
    _impl = impl

def _get():
    global _impl
    if _impl is None:
        _impl = detect()
    return _impl

def write_outputs(outputs, fallback_file=None):
    return _get().write_outputs(outputs, fallback_file)
# append_summary / notice / warning / error follow the same shape
```

Dispatch is resolved at call time, not import time, so tests swap the
implementation without patching `os.environ` before import.

### Provider semantics

`base.py` writes only to `fallback_file` and stdout/stderr. It makes the engine
runnable and testable outside any CI, which it is not today.

`github.py` is the current `gha.py` verbatim.

`gitlab.py` differs in two ways that are forced by GitLab, not chosen:

- **Output keys are normalized.** GitLab `dotenv` report keys must match
  `[A-Za-z_][A-Za-z0-9_]*`; hyphens are rejected. The engine currently emits
  `image-tags`, `secret-count`, `vault-exists`, plus `name`, `environments`,
  `docker`, `custom_tf`, `exists`, `summary`, `deployed`. The GitLab
  implementation uppercases and substitutes (`image-tags` → `IMAGE_TAGS`);
  GitHub keeps the existing spelling, so neither side changes for the other.

```python
def _key(k):
    return re.sub(r"[^A-Za-z0-9_]", "_", k).upper()

def write_outputs(outputs, fallback_file=None):
    if fallback_file:
        Path(fallback_file).write_text(_plain(outputs))
    dotenv = os.environ.get("CLOUDAPP_DOTENV")
    if dotenv:
        with open(dotenv, "a") as f:
            f.write("".join(f"{_key(k)}={v}\n" for k, v in outputs.items()))
```

- **`append_summary` degrades to a log write.** GitLab has no job-summary
  surface. This must never raise; a missing summary is not an error.

Annotations (`notice`/`warning`/`error`) degrade to prefixed log lines. Both
degradations are documented parity gaps, not defects.

`fallback_file` is the portable output path and is documented as such — it is
also what carries outputs across the container mount on GitHub (see below).

### Provider configuration

VCS and OIDC settings are deliberately **not** part of `environments/<env>.yml`.
That file describes the landing zone; which CI host is in use and what its OIDC
issuer is are properties of the driver, not of the Azure environment. Defaults
therefore live in the provider adapter itself, and environment variables
override them:

| Variable                | Default (github)                              | Default (gitlab)             |
| ----------------------- | --------------------------------------------- | ---------------------------- |
| `CLOUDAPP_CI`           | autodetected                                  | autodetected                 |
| `CLOUDAPP_VCS_ISSUER`   | `https://token.actions.githubusercontent.com` | `https://gitlab.com`         |
| `CLOUDAPP_VCS_AUDIENCE` | `api://AzureADTokenExchange`                  | `api://AzureADTokenExchange` |

Precedence is environment variable, then adapter default. Self-hosted GitLab
sets `CLOUDAPP_VCS_ISSUER` to its instance URL; nothing else changes. Entra must
be able to reach that instance's JWKS endpoint
(`https://<host>/oauth/discovery/keys`) — an air-gapped instance cannot use OIDC
federation at all, which is a documented prerequisite rather than something the
design can solve.

## Runtime image

One image carries the engine and the tools it shells out to (`terraform`, `az`,
`jq`, `yq`). Built from the monorepo and versioned with the CI drivers.

**GitLab** uses it natively:

```yaml
.cloud-app-base:
  image: ghcr.io/vgmello/cloud-app-runtime:v1
  variables:
    CLOUDAPP_CI: gitlab
    CLOUDAPP_DOTENV: cloudapp.env
  artifacts:
    reports:
      dotenv: cloudapp.env
```

**GitHub** cannot set `image:` on a composite action, so each engine step runs
the image through one shared wrapper:

```bash
cloudapp() {
  docker run --rm \
    -v "$GITHUB_WORKSPACE:/w" -w /w \
    -v "$HOME/.azure:/root/.azure" \
    -v "$(dirname "$GITHUB_OUTPUT"):/gh" \
    -e CLOUDAPP_CI=github \
    -e GITHUB_OUTPUT="/gh/$(basename "$GITHUB_OUTPUT")" \
    -e GITHUB_STEP_SUMMARY \
    ghcr.io/vgmello/cloud-app-runtime:v1 "$@"
}
```

Three details this has to get right:

- `azure/login` writes credentials to `$HOME/.azure` on the host; the mount is
  what lets the containerized engine reuse that session.
- `GITHUB_OUTPUT` and `GITHUB_STEP_SUMMARY` are host paths outside the
  workspace, so their directory is mounted and the variable is rewritten to the
  in-container path. `GITHUB_STEP_SUMMARY` needs the same treatment as
  `GITHUB_OUTPUT`; if either is on a path that cannot be mounted, the adapter's
  `fallback_file` output is read by the calling step instead.
- The wrapper is defined once and sourced by every engine step, so the mount
  list has exactly one definition.

The image removes the `pip install` and the `PYTHONPATH=…/engine python3 -m
cloudapp` path-walking currently repeated across `cloud-app/action.yml` and
`deploy-stack/action.yml`.

## Engine self-containment

`manifest.py:17` reads the schema from outside the package:

```python
SCHEMA_PATH = _PKG.parents[1] / "terraform" / "schema" / "cloud-app.schema.json"
```

The schema is the interface — the most "ours" file in the tree — while
`terraform/` becomes consumer-owned. It moves to
`engine/cloudapp/schema/cloud-app.schema.json` and is loaded as package data.
Nothing else in the engine reaches outside its own directory.

`engine/pyproject.toml` is added so the package installs normally inside the
image, replacing `requirements.txt` + `PYTHONPATH`. Dependencies are unchanged
(`pyyaml`, `jsonschema`).

## Naming contract

`naming.py` today mirrors `terraform/azure/locals.tf` — the same derivation
implemented twice. Once the Terraform is consumer-owned, an edit to `locals.tf`
silently desyncs from the engine that computes the Key Vault name
(`cloud-app/action.yml:292`) and drives `verify-deploy`.

The engine becomes the single source. It computes every resource name and emits
them in the tfvars contract:

```json
{ "config": {
    "environment": "prod",
    "platform": {…},
    "names": {
      "resource_group": "rg-orders-prod",
      "keyvault": "kv-ordersprod",
      "container_apps": {"api": "ca-orders-api-prod"},
      "function_apps": {…},
      "storage": {…},
      "database": {…}
    }
} }
```

Consumer modules read `var.config.names.*` instead of deriving. The inline
Key Vault derivation at `cloud-app/action.yml:292` is deleted and read from the
resolved tfvars. Consumers lose naming freedom in exchange for names that cannot
drift from what the engine expects; the reference module is updated to consume
`names` and documents this as part of the contract.

## Control repo and Phase 2 payload

The control repo holds `environments/`, `terraform/`, `registries/`, and the
bootstrap pipeline. It is cloned once per organization from
`control-template/` and owned by the platform team thereafter.

This forces one consequence. Phase 2 runs on the **caller's** runner and needs
both the Terraform modules and `environments/<env>.yml`, and both now live in
the control repo. So Phase 2 fetches the control repo before running Terraform.

The ref it fetches comes from two existing inputs, unchanged in meaning:
`control-repo` (which repository) and `control-ref` (which ref of it). Today
`control-ref` defaults to `github.action_ref` so the bootstrap matches the
pinned action version; after the split it defaults to the control repo's default
branch, because that repo is consumer-owned and its refs are not ours to assume.
Consumers who want a pinned control plane set `control-ref` explicitly.

The mechanism already exists: `fetch_bootstrap_cache.py` reads a file from the
control repo over the API using the App token, which already carries
`contents:read`. Phase 2 gains a shallow clone of the control repo at that same
ref, and `--terraform-dir` / `--platform-file` point into it instead of into the
action tree. On GitLab the equivalent is a clone with a project access token or
deploy key.

`environments/<env>.yml` remains platform-team-owned and is never settable from
a manifest — `state_backend` and `network` are security boundaries, and an app
team that could set them could redirect Terraform state to storage it controls
or attach to the wrong VNet.

## GitLab pipeline surface

`ci/gitlab/` mirrors `ci/github/` as CI components with typed `spec: inputs:`,
which is the closest analogue to composite-action inputs.

- **`cloud-app` component** — the Phase 2 driver. Same ~20 stages as
  `cloud-app/action.yml`: require checkout, detect manifest change, parse,
  bootstrap-or-cache, read platform config, build and push, login, state probe,
  custom terraform staging, resolve, sync secrets, apply gate, terraform or
  rotate, deploy functions, verify.
- **`bootstrap` component** — the Phase 1 target, run in the control project.

Phase 1 invocation is asymmetric on purpose. GitHub polls
(`dispatch_and_wait.py`, 279 lines) because `workflow_dispatch` has no native
wait. GitLab uses `trigger: project: … strategy: depend`, which waits natively;
reimplementing the poller there would rebuild a built-in. The bootstrap results
return through the cache file the control plane already writes
(`registries/<env>/<stack>.bootstrap.yml`), which is a durable channel on both
hosts and avoids GitLab's awkward cross-pipeline artifact fetch.

`registry.py` needs two parameters to stop being GitHub-shaped: the bot git
identity (`registry.py:99-100`, hardcoded `github-actions[bot]`) and the push
target (`origin main`, `registry.py:103-104`). The same hardcoding exists in
`deploy-stack/action.yml:225-226`.

`secrets.py:43` — "missing GitHub environment secrets" — is reworded.

## Open decision: OIDC subject shape

**This is unresolved and must be settled before implementation.** It is the only
part of the design that is a genuine security trade-off rather than plumbing.

Azure federated identity credentials match the JWT `sub` claim exactly, with no
wildcards in a standard FIC. GitHub embeds the environment in `sub`, and only
issues that token after the environment's protection rules pass:

```
repo:vgmello/orders-api:environment:prod
```

That is why `identity.py:41-43` gets a real boundary for free — the subject _is_
the approval gate. GitLab's `sub` has no environment:

```
project_path:mygroup/orders-api:ref_type:branch:ref:main
```

Environment appears in separate claims (`environment`, `environment_protected`,
`ref_protected`, `pipeline_source`) that a standard FIC cannot match on.
Consequence: on GitLab the per-environment identities (`id-<tool>-<env>-plan`
and `-apply`, already distinct) would all federate to the same subject, so any
job on the caller's default branch could assume any environment's identity. Dev
and prod stop being separated at the Entra boundary.

Three ways out, none free:

1. **GitLab-side gating.** Bind plan/apply to
   `project_path:<caller>:ref_type:branch:ref:<default>`, and rely on protected
   environments with approval rules (GitLab Premium) plus protected branches.
   The gate moves from Entra to GitLab. On GitLab Free it degrades further to a
   `when: manual` job that any Maintainer can click — materially weaker than the
   GitHub path, and it must be documented as such.
2. **Flexible FIC claims matching** (Entra preview) to match GitLab's
   `environment` claim directly. Restores parity, but depends on a preview
   feature.
3. **One control-plane project per environment**, so `project_path` itself
   carries the environment. Strongest boundary with generally-available
   features; most operational overhead.

Recommendation: (1) as the shipping default with the tier caveat documented,
(2) as an opt-in once out of preview. `identity.py` should return
`[{issuer, subject, audience}]` rather than bare subject strings regardless, and
`terraform/azure/bootstrap/main.tf:109,118` plus
`subscription-bootstrap/main.tf:83` replace their two hardcoded
`azurerm_federated_identity_credential` resources with a `for_each` over a
`federated_credentials` list variable — which removes the hardcoded issuer as a
side effect.

## Error handling

- Unknown `CLOUDAPP_CI` raises at `detect()` rather than silently falling back,
  so a typo in a pipeline variable fails loudly.
- `append_summary` never raises on any provider.
- The lock gate stays fail-closed: if the lock cannot be persisted, the deploy
  aborts (`registry.py:105-109`).
- The bootstrap cache stays fail-open: a missing or unwritable cache costs a
  bootstrap dispatch, never a failed deploy.
- A container invocation that cannot mount `GITHUB_OUTPUT` falls back to
  `fallback_file`, which the calling step reads.

## Testing

- `ci/base.py`, `ci/github.py`, `ci/gitlab.py` each get direct unit tests,
  including GitLab key normalization and the summary degradation.
- Existing engine tests run unchanged against `base` via `ci.use()`, which
  removes their current dependence on GitHub environment variables.
- `naming.py` gains golden tests for the emitted `config.names` block, and the
  reference Terraform's `locals.tf` is asserted against them so the contract
  cannot drift.
- The runtime image gets a smoke test: every `cloudapp` subcommand runs
  `--help` inside the container, catching a missing dependency or a broken
  entrypoint at build time.
- `actionlint` for GitHub stays; GitLab components are linted with
  `glab ci lint` or the CI Lint API in the monorepo's own CI.
- The GitHub wrapper's mount behavior is covered by one integration test that
  asserts outputs written inside the container are visible to the host step.

## Rollout order

1. Engine adapter (`ci/` package, 24 call sites, `gha.py` deleted). No behavior
   change; GitHub still passes.
2. Engine self-containment: schema relocation, `pyproject.toml`.
3. Naming contract: `config.names` emitted, reference module updated,
   `action.yml:292` derivation deleted.
4. Runtime image + the GitHub `docker run` wrapper. GitHub now runs on the
   image; still no GitLab.
5. Monorepo restructure and the publish pipeline for the four artifacts.
6. Control-repo template and the Phase 2 control fetch.
7. `identity.py` returns `{issuer, subject, audience}`; bootstrap Terraform
   `for_each` over `federated_credentials`.
8. GitLab components, once the OIDC decision above is made.

Steps 1-4 are pure improvements to the GitHub path and are independently
shippable. GitLab support does not begin until step 8, so the OIDC decision does
not block the majority of the work.

## Risks

- **The OIDC gap is the design's weakest point.** Under option (1) a GitLab
  deployment has a materially weaker environment boundary than the equivalent
  GitHub deployment. This must be stated in `docs/trust-modes.md`, not buried.
- **Consumer-owned Terraform means consumer-owned drift.** The `names` contract
  and the tfvars shape are the only things holding the two halves together; both
  need explicit versioning and a compatibility statement.
- **`docker run` per step adds latency** — roughly ten container starts per
  deploy on GitHub. Acceptable against the pip install and repo clone it
  replaces, but worth measuring at step 4 rather than assuming.
- **Nothing here has run against live Azure.** The platform is still offline-only
  (`README.md` status note); this design adds a second CI host to something not
  yet validated once.
