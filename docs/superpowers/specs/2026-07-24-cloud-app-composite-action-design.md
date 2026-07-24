# cloud-app: Reusable Workflow → Composite Action — Design

**Date:** 2026-07-24
**Status:** Approved
**Repo:** `vgmello/deploy`

## Overview

Convert the caller-facing `cloud-app` entrypoint from a **reusable workflow**
(`.github/workflows/cloud-app.yml`, `on: workflow_call`, four jobs) into a
single **composite action** (`.github/actions/cloud-app/action.yml`). The caller
repo owns its own workflow, its single job, and the `environment:` approval
gate; `cloud-app` is one step in that job.

The trust repo side (`.github/workflows/bootstrap.yml` + the `deploy-stack`
action) is unchanged — Phase 1 still runs in the control repo under the trusted
OIDC identity, dispatched by `cloud-app` and polled to completion.

## Motivation

The reusable-workflow form spreads work across four jobs, each on its own
runner. Because every job must `actions/checkout` `vgmello/cloud-app` into
`.deploy` to invoke the local composite sub-actions, one deploy performs **9
checkouts across the two repos** (6 in the caller runner alone) and hands
`tool.<env>.json` between jobs via an upload/download-artifact hop.

A composite action runs as steps in a single job. A `uses:`'d remote action is
fetched to `${{ github.action_path }}`, so `engine/`, `terraform/`,
`environments/`, and `.github/scripts/` are reachable **with no checkout of the
control repo**. This collapses the sprawl and removes the artifact hop.

## Goals

- `cloud-app` is a composite action invoked as one step in the caller's own
  workflow job (matches the intended topology: caller owns the workflow + gate).
- Zero control-repo checkouts; caller runner does exactly one checkout (its own
  repo, for the manifest and Dockerfile/context).
- App secrets are **explicitly enumerated** by the caller — only named values
  ever cross into the action.
- Behavior parity with today's deploy flow (bootstrap dispatch → resolve →
  secrets → terraform), plus the incidental fix below.
- Trust repo (`bootstrap.yml`, `deploy-stack`) untouched.

## Non-Goals

- No change to the engine (`python -m cloudapp ...`) beyond the secrets input
  format shim at the action boundary.
- No restructuring of the plan/apply phase model in `identity.py`.
- No change to the control repo's `bootstrap.yml` or `deploy-stack`.

## Architecture

### Caller workflow (the sample, and the documented pattern)

```yaml
name: Cloud App
on:
  push: { branches: [main] }
  pull_request:
  workflow_dispatch:
    inputs:
      environment:
        {
          description: Target environment,
          type: choice,
          options: [dev, staging, prod],
          default: dev,
        }
permissions:
  contents: read
  id-token: write
concurrency:
  group: cloud-app-${{ github.repository }}-${{ inputs.environment || 'dev' }}-${{ github.event_name == 'pull_request' && 'plan' || 'apply' }}
  cancel-in-progress: false
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment || 'dev' }} # approval gate lives here
    steps:
      - uses: actions/checkout@<pin> # caller repo: manifest + Dockerfile/context
      - uses: vgmello/cloud-app/.github/actions/cloud-app@v1
        with:
          env: ${{ inputs.environment || 'dev' }}
          plan_only: ${{ github.event_name == 'pull_request' }}
          app-id: ${{ secrets.APP_ID }}
          app-private-key: ${{ secrets.APP_PRIVATE_KEY }}
          app-secrets: |
            STRIPE_KEY=${{ secrets.STRIPE_KEY }}
```

### Action inputs (`.github/actions/cloud-app/action.yml`)

| Input             | Required              | Notes                                                   |
| ----------------- | --------------------- | ------------------------------------------------------- |
| `env`             | yes                   | Target environment.                                     |
| `manifest`        | no (`.cloud-app.yml`) | Path to the manifest in the caller repo.                |
| `plan_only`       | no (`false`)          | Plan without applying.                                  |
| `app-id`          | yes                   | GitHub App id (for the cross-repo bootstrap dispatch).  |
| `app-private-key` | yes                   | GitHub App private key.                                 |
| `app-secrets`     | no (`""`)             | Newline-delimited `NAME=value` app secrets (see below). |

Dropped relative to the old workflow: `repo_ref` (the action is pinned by the
caller's `@ref`; nothing is checked out), `secrets: inherit` (actions cannot
inherit; the caller passes `app-id`/`app-private-key`/`app-secrets` explicitly).

### Action steps (single runner, `${{ github.action_path }}`-relative)

`cloud-app` sits at `.github/actions/cloud-app`, the same directory depth as the
old sub-actions, so `../../../engine`, `../../../terraform`,
`../../../environments`, and `../../scripts` resolve identically.

1. **install** — `pip install -q -r $ACTION_PATH/../../../engine/requirements.txt`
   once (not once per sub-action).
2. **parse-manifest** — `python -m cloudapp parse-manifest` → outputs `name`,
   `docker`, `environments`; write `.cloud-app/tool.<env>.json`; validate that
   `env` is declared in the manifest.
3. **bootstrap dispatch (Phase 1)** — `create-github-app-token` (remote action)
   → `python $ACTION_PATH/../../scripts/dispatch_and_wait.py` dispatches the
   control repo's `bootstrap.yml` with `stack-name` = parsed `name`; polls to
   completion → outputs `plan_client_id`, `apply_client_id`, `resource_group`.
4. **platform** — read `$ACTION_PATH/../../../environments/<env>.yml` for
   registry / tenant / subscription / naming_prefix → keyvault name.
5. **build** (`if docker == 'true' && plan_only == false`) — `azure/login` as
   the apply identity → `python -m cloudapp docker-build` → `image-tags`.
6. **login** — `azure/login` as `plan_only ? plan_client_id : apply_client_id`.
7. **resolve** — `python -m cloudapp resolve-config` → `tfvars.json`.
8. **secrets** (`if plan_only == false`) — parse `app-secrets` → JSON map (see
   below) → engine sync; on first deploy, the existing key-vault-before-secrets
   dance (targeted `module.keyvault` apply, then re-sync with `require-vault`).
9. **deploy** — `python -m cloudapp` terraform deploy against
   `$ACTION_PATH/../../../terraform/azure` with `tfvars.json` + `image-tags`;
   write summary to `$GITHUB_STEP_SUMMARY`.

No `upload-artifact`/`download-artifact`: `tool.<env>.json` and `tfvars.json`
stay on the single runner's disk across steps.

### Secrets: explicit enumerate (option B)

The caller passes `app-secrets` as newline-delimited `NAME=value` pairs, each
value sourced from a named secret. Only enumerated values ever enter the action.

Boundary shim inside the action, before the engine call:

- Split each non-empty line on the **first** `=`: left = name, right = value.
- Build a JSON object `{name: value, ...}`.
- Feed that JSON to the existing engine secrets-sync path (the same shape the
  engine already consumes as `ALL_SECRETS`), which syncs exactly the names the
  manifest `secrets:` list declares.

Rules:

- A manifest-declared secret name absent from `app-secrets` → **fail fast**
  (caller forgot to wire it).
- Entries present in `app-secrets` but not declared in the manifest → ignored
  (optionally a warning).
- **Known limitation:** `NAME=value` lines cannot express multiline values
  (e.g. PEM). App secrets are expected to be single-line tokens. A multiline
  secret is out of scope for this format.

The engine's secrets logic is unchanged; only the action-boundary input format
differs (dotenv-style pairs → JSON map).

## OIDC / trust interaction (incidental fix)

`federation_subjects` (`engine/cloudapp/identity.py`) federates:

- **plan** identity → `repo:<app>:pull_request` **and** `repo:<app>:environment:<env>`
- **apply** identity → `repo:<app>:environment:<env>`

Today the `build` job has no `environment:`, so its `azure/login` for the ACR
push presents a ref-based subject (`repo:<app>:ref:...`) that the apply
identity's federation does **not** trust — a latent break (the platform is
"wired, not yet live-validated").

In the single gated job every `azure/login` presents
`repo:<app>:environment:<env>`, which both identities trust. Consolidation
removes the mismatch as a side effect. No terraform/federation change required.

## Files

**New**

- `.github/actions/cloud-app/action.yml` — the composite action.

**Removed** (logic absorbed into the composite action; used only by the old
`cloud-app.yml`):

- `.github/workflows/cloud-app.yml`
- `.github/actions/parse-manifest/`
- `.github/actions/docker-build/`
- `.github/actions/resolve-config/`
- `.github/actions/sync-secrets/`
- `.github/actions/terraform-deploy/`
- `.github/actions/cloudapp-dispatch-workflow/`

**Unchanged** — `.github/workflows/bootstrap.yml`, `.github/actions/deploy-stack/`,
`engine/` (modulo the secrets boundary shim living in the action, not the
engine), `terraform/`, `environments/`.

**Updated**

- `samples/caller-app/.github/workflows/cloud-app.yml` — full caller workflow
  (own job, `environment:` gate, explicit `app-secrets`).
- Docs referencing the reusable-workflow form: `README.md`, `docs/usage.md`,
  `registries/README.md`, `samples/caller-app/README.md`.

## Checkout accounting

|                                                   | Before | After                    |
| ------------------------------------------------- | ------ | ------------------------ |
| Caller runner                                     | 6      | 1 (caller self-checkout) |
| Control runner (`bootstrap.yml` + `deploy-stack`) | 3      | 3 (unchanged)            |
| **Total per deploy**                              | **9**  | **4**                    |

## Trade-offs accepted

- `build` and `deploy` serialize as steps in one job (lose cross-job
  parallelism). Acceptable: build already gates deploy via `needs`.
- Caller wires `app-id` / `app-private-key` / `app-secrets` explicitly instead
  of `secrets: inherit`. More explicit, and required for the tighter secret
  scoping.
- Caller must keep `app-secrets` in sync with the manifest `secrets:` list;
  fail-fast on a missing name limits the blast radius of drift.

## Testing

- Engine behavior is already covered by `engine/tests/` and is unchanged.
- Add a small unit test for the `app-secrets` `NAME=value` → JSON map parser
  (first-`=` split; blank-line skip; missing manifest name → error) at whatever
  layer hosts the shim (engine helper preferred over inline bash so it is
  testable).
- Manual/live validation of the full action remains gated on a real deploy
  (consistent with the platform's current "wired, not yet live-validated"
  status).
