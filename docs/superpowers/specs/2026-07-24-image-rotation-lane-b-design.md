# Lane B: Direct Image Rotation — Design

**Date:** 2026-07-24
**Status:** Approved
**Repo:** `vgmello/cloud-app`

## Overview

The `cloud-app` composite action already gates the Terraform run on
`always_run_terraform` (default false): on a routine apply whose manifest did
not change since the previous commit, the gate sets `should_apply=false` and the
Terraform run is skipped. The Docker image is still rebuilt every run, but today
nothing ships it on the skip path.

This phase implements **Lane B**: on the skip path, update the running Azure
container images directly (`az containerapp update` / `az functionapp config
container set`) — rolling a new revision that picks up the new image without a
Terraform run.

Two lanes, both after the always-on Docker build:

- **Lane A** (`should_apply == true`) — manifest changed, first deploy, manual
  dispatch, or `always_run_terraform: true` → Terraform `plan + apply` carries
  the new image via `image_tags`. Unchanged; already built.
- **Lane B** (`should_apply == false`) — manifest unchanged → skip Terraform,
  rotate images directly. This phase.

## Goals

- On the Lane B skip path, deploy the freshly built images by updating the
  existing Azure Container Apps and Function Apps in place.
- Cover every docker-built image in `image_tags` — container-app containers and
  functions (both are container-image based here).
- No Terraform, no `terraform init`, no plan on Lane B.
- Names resolved deterministically in the engine (mirroring `locals.tf`),
  unit-tested against the Terraform naming.

## Non-Goals

- **Static sites** — no container image; never appear in `image_tags`. A
  static-content change with an unchanged manifest is not rotated (needs a
  manifest change or `always_run_terraform: true`). Documented, out of scope.
- **Force-restart on same-sha secret rotation** — deferred. The image tag is
  `git.sha`; every real run carries a new commit (consumers path-filter on
  `src/**` + the manifest), so a new sha → `az ... update` sets a different
  image → new revision → version-less Key Vault refs re-read → rotated secrets
  picked up automatically. The only stuck case is redeploying the exact same sha
  after rotating a secret (a re-run), which does not occur in the consumer
  workflow. Workaround documented: push a commit or `az containerapp revision
restart`.
- No change to Terraform, the trust repo, or Lane A.

## Background: how images and names work today

`engine/cloudapp/builds.py` — `image_tags` contract:

- key `"<app_key>/<container_key>"` for app containers; `"<function_key>"` for
  functions (a function key never contains `/`).
- value `"<registry>/<name>/<key-with-'/'->'-'>:<sha>"`.
- Containers/functions with an explicit `image:` are excluded (nothing to
  rotate; they change only via the manifest → Lane A).

Terraform naming (`terraform/azure/locals.tf`):

- `base = naming_prefix + cfg.name`
- `app_base(k)  = coalesce(app.name, len(apps)==1 ? base : "base-<k>")`
- `func_base(k) = coalesce(fn.name,  len(functions)==1 ? base : "base-<k>")`
- container app name = `"ca-<app_base>-<env>"` (resource `azurerm_container_app.name`)
- container name = the manifest container key (`container.key`)
- function app name = `"func-<func_base>-<env>"` (resource `azurerm_linux_function_app.name`)

Container image (`modules/container-app/main.tf:79`) =
`var.image_tags[container.key]`; function image (`modules/function/main.tf:13`)
= `var.image_tag`. Both reference Key Vault secrets **version-less**
(`secrets/<name>` / `SecretUri=.../<name>/`), so a new revision re-reads the
latest secret value.

## Architecture

### Engine

**`engine/cloudapp/naming.py`** (new) — pure functions mirroring `locals.tf`:

```
base(tool, prefix)                    -> f"{prefix}{tool['name']}"
container_app_name(tool, prefix, env, app_key)   -> f"ca-{app_base}-{env}"
function_app_name(tool, prefix, env, func_key)   -> f"func-{func_base}-{env}"
```

where `app_base` / `func_base` follow the coalesce rule above (explicit `name`
→ single-entry `base` → `base-<key>`). `prefix` is `platform.naming_prefix` or
`""`. No `az`, no I/O — deterministic from the tool config + prefix + env.

**`cloudapp rotate-images` CLI command** (new, `cli.py` + a `rotate.py` module):

```
python3 -m cloudapp rotate-images
  --tool-json .cloud-app/tool.<env>.json
  --environment <env>
  --platform-file <platform env yml>     # for naming_prefix
  --image-tags '<json map>'              # from docker-build
  --resource-group <rg>                  # from the bootstrap output
```

Behavior — for each `(key, image)` in `image_tags`:

- key contains `/` → `app_key, container_key = key.split("/", 1)`; resolve
  `name = container_app_name(...)`; run
  `az containerapp update --name <name> --resource-group <rg> --container-name <container_key> --image <image>`.
- key has no `/` → function; resolve `name = function_app_name(...)`; run
  `az functionapp config container set --name <name> --resource-group <rg> --image <image>`.

Each `az` call goes through `runner.run(..., check=False, capture=True)`; a
non-zero exit raises `RotateError` naming the resource. Prints one line per
rotated image and a final count. An empty `image_tags` map is a no-op (nothing
was built).

`RotateError` is added to the CLI's caught-exception tuple so failures surface
as a clean GHA `::error::` annotation.

### Action (`.github/actions/cloud-app/action.yml`)

One new step, on the Lane B skip path, after the gate:

```yaml
- name: Rotate images
  id: rotate
  if: ${{ steps.gate.outputs.should_apply == 'false' }}
  shell: bash
  env:
    DEPLOY_ENV: ${{ inputs.env }}
    IMAGE_TAGS: ${{ steps.build.outputs.image-tags || '{}' }}
  run: >-
    PYTHONPATH="${{ github.action_path }}/../../../engine"
    python3 -m cloudapp rotate-images
    --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
    --environment "$DEPLOY_ENV"
    --platform-file "${{ steps.platform.outputs.file }}"
    --image-tags "$IMAGE_TAGS"
    --resource-group "${{ steps.bootstrap.outputs.resource_group }}"
```

- `should_apply == 'false'` is reachable only on a non-plan-only apply run with
  an unchanged manifest and existing state — so exactly one of `Terraform deploy`
  (`should_apply == 'true'`) and `Rotate images` runs.
- Uses the already-completed `Azure login (deploy)` (apply identity, RG
  Contributor — can update container apps / function apps).
- `IMAGE_TAGS` comes from the `Build image` step, which runs on Lane B
  (`docker == 'true' && plan_only == 'false'`). If the stack has no docker
  builds, `image_tags` is `{}` and rotation is a no-op.
- `Write summary`'s skip branch is updated to report that image rotation ran
  (replacing the current "rotation pending" text).

### Why Lane B is safe by construction

Lane B runs only when `should_apply == false`, which requires the manifest to be
provably unchanged **and** Terraform state to already exist (first deploy forces
Lane A via the `state-exists` probe). So the exact app/container/function set was
applied by a prior Terraform run and exists in Azure — every computed name
resolves. Adding or removing an app/container/function is a manifest change →
Lane A.

## Files

**New**

- `engine/cloudapp/naming.py` — name derivation.
- `engine/cloudapp/rotate.py` — rotation logic (`rotate`, `RotateError`).
- `engine/tests/py/test_naming.py`
- `engine/tests/py/test_rotate.py`

**Modified**

- `engine/cloudapp/cli.py` — `cmd_rotate_images` + `rotate-images` subparser;
  add `rotate.RotateError` to the caught-exception tuple.
- `.github/actions/cloud-app/action.yml` — `Rotate images` step + updated skip
  summary.
- `samples/caller-app/README.md` / docs — a line on the two lanes and the static
  site / same-sha-secret caveats.

## Testing

- `test_naming.py`: single app (`ca-orders-api-dev`), multi-app suffixing
  (`ca-<base>-<key>-dev`), `naming_prefix`, explicit `name` override, and a
  function name (`func-...-dev`). Assert equality with the Terraform naming for
  the shared fixtures.
- `test_rotate.py`: with a fake `run`, assert the exact `az` argv for a
  container-app key (`containerapp update --container-name`) and a function key
  (`functionapp config container set`), correct computed names, empty-map
  no-op, and that a non-zero `az` exit raises `RotateError`.
- Full engine suite + `ruff` stay green.
- GitHub Actions execution remains statically validated (YAML parse) +
  gated on a live deploy, consistent with the platform's status.

## Rollout note

Lane B is inert until a run hits `should_apply == false` (unchanged manifest,
existing state). First deploys and manifest changes are unaffected (Lane A).
