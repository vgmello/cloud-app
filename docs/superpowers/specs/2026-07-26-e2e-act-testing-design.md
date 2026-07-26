# Workflow end-to-end testing with `act` and a fake Azure

**Date:** 2026-07-26
**Status:** approved

## Problem

Every line of deploy logic in this repo is tested in isolation, and none of it
is tested as a running workflow.

- `engine/tests/py` tests `cloudapp` with `run` injected as a fake. It never
  invokes `az`, `terraform`, or `docker`.
- `terraform/azure/tests` tests the modules with mocked providers. It never
  sees a `tfvars.json` produced by `cloudapp resolve-config`.
- Nothing tests `.github/actions/cloud-app/action.yml` or
  `.github/actions/deploy-stack/action.yml` at all. Those two files hold 786
  lines of step wiring, `if:` gating, output plumbing, and shell — the layer
  where a typo is invisible until a real deploy fails.

The gap is the seam. Unit tests prove each function is right; nothing proves
they are wired together right.

## Goal

Run the real composite actions, unmodified, inside a container, against a
substitute Azure, and assert on what they did.

Explicitly _not_ a goal: testing Azure, or testing Terraform. Those stay
covered where they already are.

## Constraint: no Azure control-plane emulator exists

Azurite emulates Blob, Queue, and Table. Container Apps, Key Vault, Function
Apps, Postgres, and managed identities have no local emulator, official or
otherwise. LocalStack is AWS-only.

The design therefore splits the substitute by what can be real:

| Surface                | Substitute                           | Fidelity                    |
| ---------------------- | ------------------------------------ | --------------------------- |
| Blob storage           | **Azurite**                          | real                        |
| Terraform state blob   | **Azurite**, written by the shim     | real storage, fake contents |
| `az` control plane     | JSON resource graph                  | behavioural double          |
| `terraform` plan/apply | shim rendering tfvars into the graph | behavioural double          |
| `docker` build/push    | recording shim                       | call assertions only        |
| GitHub API             | local HTTP server                    | behavioural double          |

Calling this "e2e" means **workflow e2e**: the whole action executes for real,
and the cloud beneath it does not. That distinction is stated in `CLAUDE.md`
so nobody reads a green suite as proof the platform deploys.

## Architecture

```
pytest (host)
  ├── starts Azurite container
  ├── starts fakegh HTTP server
  └── runs `gh act -W tests/e2e/workflows/<scenario>.yml`
        └── act container (catthehacker/ubuntu:act-latest)
              ├── PATH prepended with tests/e2e/fakecloud/bin
              │     ├── az        → Azurite (storage) + graph.json (control plane)
              │     ├── terraform → state blob in Azurite + graph.json
              │     └── docker    → recorder
              ├── --local-repository swaps remote actions for tests/e2e/stubs
              └── GITHUB_API_URL → fakegh
  └── asserts on graph.json, *-calls.jsonl, act stdout
```

The state directory lives inside the repo tree, which act bind-mounts, so
everything written inside the container is readable by pytest on the host with
no artifact plumbing.

### Fake cloud

`tests/e2e/fakecloud/bin/az` dispatches on the argv prefix. The complete set of
`az` invocations in the engine is known and closed:

| Command                                                                      | Behaviour                                                                  |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `storage blob exists`                                                        | real Azurite lookup; translates `--auth-mode login` to a connection string |
| `keyvault show`                                                              | graph lookup; exits non-zero with a `ResourceNotFound` stderr when absent  |
| `keyvault secret show` / `set`                                               | graph read/write                                                           |
| `keyvault network-rule add`                                                  | graph write                                                                |
| `containerapp show` / `revision show` / `update`                             | graph                                                                      |
| `functionapp show` / `config container set` / `deployment source config-zip` | graph                                                                      |
| `acr login`, `login`, `account set`                                          | no-op                                                                      |

Anything unrecognised exits non-zero and is logged, so an engine change that
adds a new `az` call fails loudly rather than silently passing.

`bin/terraform` handles `init`, `plan`, `apply`, `show`, `output`. `init`
records the `-backend-config` lines it received (which is how
`backend.render()` gets verified against a real storage account) and creates
the container in Azurite. `apply` reads `tfvars.json`, derives resource names
via the same rules as `terraform/azure/locals.tf`, writes them into the graph,
and writes the state blob. `plan` emits the summary line `tfdeploy` parses.
`output -json names` serves what `funcdeploy` needs.

`bin/docker` records `build`/`tag`/`push` and exits 0. No registry: colima's
daemon cannot be given an insecure-registry entry from inside a test, and
serving TLS for a fake ACR is more machinery than the coverage justifies. The
upgrade path to a real `registry:2` service is documented, not built.

### Scenario control

Shims read `tests/e2e/state/scenario.json`, written by pytest before the run.
It seeds the graph (pre-existing state blob, pre-existing vault) and can arm
failures (`containerapp` stuck in `Failed`, `keyvault secret set` failing
once). That is what makes the negative paths — verify-fails, RBAC retry —
testable without touching engine code.

### Stubbed remote actions

act's `--local-repository` maps `owner/repo@ref` to a directory:

- `actions/checkout` → copies a fixture repo into the requested `path`
- `actions/create-github-app-token` → emits a fixed token
- `azure/login` → no-op (the `az` shim needs no credentials)
- `actions/upload-artifact` → copies into a directory fakegh serves
- `hashicorp/setup-terraform`, `actions/setup-python` → no-op (the image has both)

### Fake GitHub API

`tests/e2e/fakegh/server.py` serves only the endpoints the two scripts call:
repo contents (bootstrap cache), workflow dispatch, run status, run jobs,
artifact list, and artifact zip download.

A dispatch returns a seeded result rather than recursively running the
control-side harness under act. Nesting act inside act would need
docker-in-docker, and it would buy nothing: the caller side already exercises
the dispatch boundary through this server, and the control side is driven
directly by `test_deploy_stack.py`. Both halves are covered; only the wire
between them is seeded.

## Corrections applied during the build

Recorded because each cost real debugging time and none is obvious from act's
documentation:

- Only `act --env` beats act's built-in `GITHUB_*` values. Setting
  `GITHUB_API_URL` in workflow- or job-level `env:` is silently overridden;
  step-level `env:` wins for that step but the design needed it inside a
  composite action's steps.
- act silently no-ops an `actions/checkout` that declares no `repository:`,
  so `deploy-stack`'s `central-workspace/` was never created. The suite passes
  `--no-skip-checkout`.
- Scenarios drive `push`, not `workflow_dispatch`. The action forces both the
  bootstrap dispatch and the apply on a manual dispatch, which hid the
  cache-hit and rotate lanes entirely.
- The container architecture is not pinned. Emulating linux/amd64 on Apple
  silicon made a single scenario take 5m32s instead of 24s, because a
  composite action shells out to `python3` a couple of dozen times.

## The one implementation change

`dispatch_and_wait.py` and `fetch_bootstrap_cache.py` hardcode
`API = "https://api.github.com"`. Both become:

```python
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
```

`GITHUB_API_URL` is a standard variable GitHub Actions already sets on every
runner, so this is the idiomatic form regardless of testing. The alternative —
a local CA plus an `/etc/hosts` override inside the container — was rejected as
disproportionate.

Nothing else outside `tests/`, `CLAUDE.md`, `.actrc`, and a new
`.github/workflows/e2e.yml` is touched. `ci.yml` is deliberately left alone:
two other branches are in flight against it and a new job there would conflict.

## Scenarios

**cloud-app action**

1. `first-deploy` — no state blob → gate reports first deploy → targeted
   keyvault apply → secret sync → full apply → state blob exists in Azurite
   afterwards.
2. `unchanged-manifest` — state blob seeded, manifest identical to `HEAD^` →
   `should_apply=false` → no `terraform` call, `az containerapp update` called
   with the new tag.
3. `plan-only` — no apply, no secret sync, no rotation, summary is `plan only`.
4. `custom-terraform` — sample app's `terraform/queue.tf` staged into the
   custom module; `custom_tf=true` forces the apply even on an unchanged
   manifest.
5. `code-functions` — `runtime:` function packaged and shipped via
   `config-zip` after apply.
6. `verify-fails` — revision armed `Failed`; the run fails with the resource
   named in the error.
7. `cache-hit` — bootstrap cache matching `bootstrap.fingerprint` → no
   dispatch, identities come from the cache.

**deploy-stack action**

8. `lock-tofu` — unregistered stack registers a lock under
   `registries/<env>/<stack>.yml`.
9. `unauthorized-caller` — a different repo claiming a registered stack is
   rejected with the SECURITY VIOLATION message.
10. `bootstrap-outputs` — `deployment-results.json` carries RG and both client
    ids; the bootstrap cache file is written.

**Terraform state**

11. `state-roundtrip` — `backend.render()` output drives a real Azurite
    container/blob; `state_exists` is false before and true after, and false
    for a different `(name, env)` pair.

**act smoke**

12. `ci.yml` and `site.yml` run under act, so workflow-level regressions are
    catchable locally before push.

## Layout

```
.actrc
tests/e2e/
  conftest.py            Azurite + fakegh fixtures, act driver
  test_cloud_app.py      scenarios 1-7
  test_deploy_stack.py   scenarios 8-10
  test_state_backend.py  scenario 11
  test_act_smoke.py      scenario 12
  fakecloud/
    bin/{az,terraform,docker}
    graph.py             shared resource-graph helpers
  fakegh/server.py
  stubs/<action>/action.yml
  workflows/*.yml        harness workflows (outside .github/, never scheduled)
  fixtures/caller-repo/  git repo fixture for checkout stubs
  state/                 gitignored; graph.json, *-calls.jsonl, scenario.json
```

`tests/e2e` is outside `engine/`, so the existing `--cov-fail-under=90` gate on
`cloudapp` is unaffected. E2E is selected by its own path, not a marker, so
`pytest engine/tests/py` keeps its current meaning.

## Running

```bash
pytest tests/e2e                 # everything (needs Docker)
pytest tests/e2e -k first_deploy # one scenario
```

`.actrc` pins `--container-architecture linux/amd64` (required on Apple
silicon) and the runner image.

## Risks

- **The `terraform` shim is a double.** It validates the action's wiring
  around Terraform, not Terraform's behaviour. Module behaviour stays covered
  by `terraform test`. If the shim and the real modules drift, the suite goes
  green on a broken deploy. Mitigated by deriving names from the same rules as
  `locals.tf` and by scenario 11 exercising the real backend config.
- **`runner.fetch_runner_ip` calls `https://api.ipify.org`.** `dev.yml` sets
  `runner_access: public-allowlist`, so this fires. Left as real network; it
  costs one request and degrades to `None` after 15s offline.
- **act on Apple silicon under emulation is slow.** Full suite is minutes, not
  seconds. CI runs it on native amd64.
- **Scenarios will fail until the two in-flight branches merge.** That is
  expected and the reason this lands as tests-only; fixes come after the merge
  into `deploy-3`.
