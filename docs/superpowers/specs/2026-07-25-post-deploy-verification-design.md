# Post-Deploy Verification — Design

**Date:** 2026-07-25
**Status:** Approved
**Repo:** `vgmello/cloud-app`

## Overview

After a deploy, verify against Azure that the resources the manifest declares
actually exist and are healthy. Fail the run when they are not.

This closes the last silent failure path in the two-lane deploy model and, more
valuably, catches a broken image that deploys successfully but crash-loops —
something no gate or bookkeeping signal can detect.

## Motivation

The `cloud-app` action has two mutually exclusive paths out of the `Decide
apply` gate:

- **Lane A** (`should_apply == 'true'`) — `Terraform deploy` runs.
- **Lane B** (`should_apply == 'false'`) — Terraform is skipped entirely and the
  freshly built image is rolled onto existing resources by `Rotate images`.

Lane B's safety rests on the assumption that the resources it patches already
exist. That assumption is inherited from the gate, which treats "the Terraform
state blob exists" as "the stack is fully built" — but the first-deploy
key-vault targeted apply writes the state blob _before_ any workload resource
exists. A first deploy that dies after that point leaves a stack that
permanently qualifies for Lane B.

In the common case this is loud: `az containerapp update` against an app
Terraform never created fails, and the operator recovers by re-running with
`always_run_terraform: true`. **The exception is a stack with nothing to
rotate** — every container pinned via `image:`, so `builds.py` excludes them all
and `image_tags` is `{}`. `rotate.py` then iterates an empty map, exits 0, and
the run reports success having deployed nothing, over half-built
infrastructure. Nothing fails, so nobody knows to recover.

Rather than add another derived signal that can disagree with reality — the
failure mode behind both defects found this week (`state-exists ≠ fully built`;
`normalize ≠ injective`) — verify the actual resources.

## Goals

- A missing declared resource fails the run (closes the silent path).
- An unhealthy revision fails the run (catches a broken image after either lane).
- No new persisted state, marker, or cached signal.
- No false failure for a legitimately idle scale-to-zero app.

## Non-Goals

- Not a gate: this runs _after_ deploying, it does not decide whether to deploy.
- No rollback. Failing the run is the outcome; recovery is the operator's call.
- Static sites are not verified (no revisions, no image).
- Does not replace the `always_run_terraform` recovery lever, which ships
  alongside it.

## Design

### When it runs

A new `Verify deployment` step in `.github/actions/cloud-app/action.yml`, after
both `Terraform deploy` and `Rotate images`, gated on `inputs.plan_only ==
'false'` and `inputs.verify_deploy != 'false'`. It deliberately runs on **both**
lanes and even when neither did anything — that is precisely what makes the
silent case loud.

It uses the Azure session already established by `Azure login (deploy)` and the
resource group from `steps.bootstrap.outputs.resource_group`.

### What it checks

Resource names are derived with the existing `naming` helpers, so the check
targets exactly what Terraform created.

**Container apps** — for each key in `tool["apps"]`, name via
`naming.container_app_name`:

1. The app must exist. `az containerapp show` failing with a not-found is the
   half-built-stack case and is reported as such.
2. Its latest revision must have `provisioningState == "Provisioned"`.
3. If that app's `replicas.min > 0`, the revision must additionally report
   `runningState == "Running"`. When `replicas.min == 0` the app may legitimately
   be idle, so provisioned-but-not-running passes.

**Function apps** — for each key in `tool["functions"]`, name via
`naming.function_app_name`: the app must exist and report `state == "Running"`.

**Static sites** — skipped.

### Polling

A revision is not healthy the instant a deploy returns, so the check polls until
every resource passes or the budget expires: every 10 seconds, up to
`verify_timeout` seconds (default `300`). A resource that reaches a terminal
failure state (`provisioningState == "Failed"`) fails immediately rather than
burning the budget.

On failure the error names the resource, the revision, and the observed state,
so the operator can go straight to logs:

```
::error::cloud-app: ca-orders-api-dev revision ca-orders-api-dev--abc123 is
provisioningState=Provisioned runningState=Degraded after 300s. Check container
logs; re-run with always_run_terraform: true if the stack is incomplete.
```

### Inputs

| Input            | Default  | Notes                                                |
| ---------------- | -------- | ---------------------------------------------------- |
| `verify_deploy`  | `"true"` | Set `false` to skip verification entirely.           |
| `verify_timeout` | `"300"`  | Seconds to wait for all resources to become healthy. |

### Engine

**`engine/cloudapp/verify.py`** (new) — the `run` seam is injected, as in
`rotate.py` / `backend.py`, so everything is unit-testable without Azure.

- `expected_resources(tool, prefix, env) -> list[dict]` — pure. Returns one
  entry per verifiable resource: `{"kind": "containerapp"|"functionapp",
"name": str, "require_running": bool}`. `require_running` is
  `replicas.min > 0` for apps and always `True` for functions. Static sites are
  omitted.
- `check_resource(resource, resource_group, run) -> tuple[bool, str]` — one
  resource, one probe. Returns `(healthy, detail)`; `detail` is the human-readable
  state used in the error.
- `verify(tool, prefix, env, resource_group, run, timeout=300, sleep=time.sleep)`
  — polls `check_resource` for every entry until all pass, a terminal failure is
  seen, or the budget expires. Raises `VerifyError` naming the failing resources.

`VerifyError` joins the caught-exception tuple in `cli.main` so failures surface
as a clean `::error::` annotation rather than a traceback.

**CLI:** `cloudapp verify-deploy --tool-json --environment --platform-file
--resource-group [--timeout]`. `prefix` comes from the platform file's
`naming_prefix`, matching `cmd_rotate_images`.

## Files

**New**

- `engine/cloudapp/verify.py`
- `engine/tests/py/test_verify.py`

**Modified**

- `engine/cloudapp/cli.py` — `cmd_verify_deploy`, subparser, `VerifyError` in the
  exception tuple.
- `.github/actions/cloud-app/action.yml` — `verify_deploy` / `verify_timeout`
  inputs; `Verify deployment` step.
- `samples/caller-app/.github/workflows/cloud-app.yml` — add an
  `always_run_terraform` boolean `workflow_dispatch` input wired to the action
  input (the recovery lever).
- `samples/caller-app/README.md`, `docs/usage.md` — document verification and the
  recovery procedure.

## Testing

All engine tests drive a fake `run`; no Azure.

- `expected_resources`: apps and functions included with correct names and
  `require_running`; `replicas.min == 0` yields `require_running False`; static
  sites excluded; a manifest with neither apps nor functions yields `[]`.
- `check_resource`: healthy container app passes; missing app (az non-zero,
  not-found) fails with a not-found detail; `runningState == "Degraded"` fails
  when `require_running`, passes when not; function app `Running` passes,
  `Stopped` fails.
- `verify`: passes when everything is healthy on the first poll; retries and
  then passes when a resource becomes healthy on a later poll (asserting `sleep`
  was called); raises `VerifyError` naming the resource when the budget expires;
  fails fast on `provisioningState == "Failed"` without exhausting the budget;
  empty resource list is a no-op.
- CLI: `verify-deploy` wires the arguments through and surfaces `VerifyError` as
  an error annotation.
- Full engine suite + `ruff` green. The action is validated by YAML parse; the
  `az` behaviour itself is only exercised on a live deploy, consistent with the
  platform's status.

## Rollout note

Verification is on by default. The first deploys after this ships will begin
failing on stacks that were already broken — which is the intent, and the error
names the recovery. `verify_deploy: false` is the escape hatch if a stack needs
to deploy while known-unhealthy.
