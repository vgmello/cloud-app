# cloud-app

A deployment platform: app teams describe a stack in `cloud-app.yml`, a
composite GitHub Action turns it into Terraform and deploys it to Azure. See
`README.md` for the product and `docs/usage.md` for the manifest reference.

## Layout

| Path                            | What                                                                |
| ------------------------------- | ------------------------------------------------------------------- |
| `engine/cloudapp/`              | All action logic (parse, resolve, build, secrets, deploy, verify)   |
| `.github/actions/cloud-app/`    | Caller-side composite action (Phase 2: the resource deploy)         |
| `.github/actions/deploy-stack/` | Control-side composite action (Phase 1: RG + plan/apply identities) |
| `.github/scripts/`              | Standalone scripts the actions shell out to                         |
| `terraform/azure/`              | Root module, compute and shared child modules                       |
| `environments/`                 | Per-environment platform config                                     |
| `registries/`                   | Stack-lock registry (who owns which stack name)                     |
| `tests/e2e/`                    | Workflow e2e suite (see below)                                      |

## Testing

Three tiers. They test different things and none of them substitutes for
another.

| Tier         | Command                                 | What it proves                                                                    |
| ------------ | --------------------------------------- | --------------------------------------------------------------------------------- |
| Unit         | `cd engine && pytest tests/py`          | Each function's logic, with `run` injected as a fake. No process is ever spawned. |
|              | `pytest .github/scripts/tests`          | The standalone scripts, with `urlopen` patched.                                   |
| Module       | `terraform -chdir=terraform/azure test` | Module logic against mocked providers. Offline.                                   |
| Workflow e2e | `pytest tests/e2e`                      | The composite actions running as real workflows.                                  |

Run all three before claiming something works. The unit tier is fast enough to
run constantly; the e2e tier takes a few minutes.

### What "e2e" means here

The composite actions run **for real**, unmodified, inside a container. The
cloud beneath them does not exist.

There is no Azure control-plane emulator. Azurite covers Blob, Queue and Table;
Container Apps, Key Vault, Function Apps and Postgres have nothing. So the
substitute is split by what can be genuine:

| Surface              | Substitute                                         | Fidelity                         |
| -------------------- | -------------------------------------------------- | -------------------------------- |
| Blob storage         | Azurite container                                  | real                             |
| Terraform state blob | Azurite, written by the shim                       | real storage, synthetic contents |
| `az` control plane   | JSON resource graph (`tests/e2e/fakecloud/bin/az`) | behavioural double               |
| `terraform`          | shim (`tests/e2e/fakecloud/bin/terraform`)         | behavioural double               |
| `docker`             | recording shim                                     | call assertions only             |
| GitHub REST API      | local server (`tests/e2e/fakegh/`)                 | behavioural double               |

**A green e2e run does not mean the platform can deploy to Azure.** It means
the action drives its tools correctly: right steps, right order, right gating,
right identity, right backend config, right handling of what those tools
return. Module behaviour stays covered by `terraform test`; nothing here has
been run against a live subscription.

The `terraform` shim is the weakest link — it is a double of Terraform itself.
If it drifts from the real modules, the suite can go green on a broken deploy.
It mirrors `terraform/azure/locals.tf` for naming, and
`tests/e2e/fakecloud/naming.py` re-implements those rules independently rather
than importing `cloudapp.naming`, so a divergence between the two fails the
suite instead of agreeing with itself.

### Running it

```bash
pytest tests/e2e                      # everything (needs Docker)
pytest tests/e2e -k first_deploy      # one scenario
pytest tests/e2e/test_cloud_app.py    # one suite
E2E_RUN_WORKFLOWS=1 pytest tests/e2e/test_act_smoke.py   # execute ci.yml for real
```

The suite starts and stops Azurite and the fake GitHub API itself, on a fixed
docker network with fixed container names. **It must stay serial** — do not run
it with `-n`/xdist.

Each scenario builds a scratch workspace under `tests/e2e/.work/<test name>/`
that looks like a caller repo with the platform installed into it. After a run,
that directory holds everything needed to debug:

| File                                    | What                                             |
| --------------------------------------- | ------------------------------------------------ |
| `tests/e2e/state/act.log`               | The full act invocation and its output           |
| `tests/e2e/state/graph.json`            | The fake cloud's resources at the end of the run |
| `tests/e2e/state/az-calls.jsonl`        | Every `az` invocation, in order                  |
| `tests/e2e/state/terraform-calls.jsonl` | Every `terraform` invocation                     |
| `tests/e2e/state/dispatches.jsonl`      | Every workflow dispatch that was sent            |
| `tests/e2e/state/azure-logins.jsonl`    | Which identity each login used                   |

### Adding a scenario

1. Pick or add a caller manifest in `tests/e2e/fixtures/caller/`.
2. Write a test taking the `workspace` fixture. Use
   `@pytest.mark.workspace(commits=[...])` to control git history — one entry
   per commit, `None` for an empty commit (that is how "manifest unchanged" is
   set up).
3. Seed before running: `workspace.seed_state_blob(...)` to make a stack look
   deployed, `workspace.fakegh(contents={...})` for a bootstrap cache entry,
   `workspace.scenario(...)` to arm a failure (a crash-looping revision, a
   transient authz error, a failing secret write).
4. `workspace.act("deploy.yml", {...}, expect_success=True)`, then assert on
   the graph and call logs.

If the action starts calling an `az` subcommand the shim does not know, the
shim exits 64 and the scenario fails loudly. Add the command to
`tests/e2e/fakecloud/bin/az` rather than working around it.

### act quirks worth knowing

These cost real debugging time; they are not obvious from act's docs.

- **`--container-daemon-socket -` is mandatory on colima.** act bind-mounts the
  Docker socket by default and colima's socket path cannot be mounted
  (`operation not supported`). Nothing here needs a real daemon — `docker` is
  shimmed. Already set in `.actrc`.
- **Only `--env` beats act's built-in `GITHUB_*` values.** act injects
  `GITHUB_API_URL` after workflow- and job-level `env:`, so setting it there
  does nothing. `--env` wins and, unlike step-level `env:`, reaches the steps
  inside a composite action.
- **act silently no-ops an `actions/checkout` with no `repository:`.** It
  assumes the workspace is already the repo. `deploy-stack` relies on exactly
  that step to populate `central-workspace/`, so the suite passes
  `--no-skip-checkout`.
- **Do not pin `linux/amd64` on Apple silicon.** act suggests it, but emulating
  x86 makes every `python3` invocation about 5x slower, and a composite action
  makes a couple of dozen of them — the suite went from 3 minutes to over 25.
  `.actrc` leaves the architecture unpinned and the suite passes the host's;
  for manual runs add `--container-architecture linux/arm64`.
- **`workflow_dispatch` is not a neutral event.** The action forces both the
  bootstrap dispatch and the Terraform apply on a manual dispatch, which hides
  the cache-hit and rotate lanes. Scenarios drive `push` unless the force path
  is what is being tested.
- **The act runner image has a Debian-managed Python**, so PEP 668 rejects the
  action's `pip install`. GitHub's hosted runners do not. The suite sets
  `PIP_BREAK_SYSTEM_PACKAGES=1`; this papers over an image difference, not a
  product bug.

## Conventions

- Cloudflare config in `wrangler.toml` (TOML), never JSON.
- Pin every third-party action to a full commit SHA with the version in a
  trailing comment.
- Keep `bootstrap.fingerprint` in sync: `PYTHONPATH=engine python3 -m cloudapp
bootstrap-fingerprint --root . > bootstrap.fingerprint`. CI fails on drift.
- Regenerate Terraform test fixtures with `python3 engine/generate_tf_fixtures.py`
  after changing manifest resolution. CI fails on drift.
