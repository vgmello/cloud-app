# cloud-app Composite Action Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four-job reusable workflow `.github/workflows/cloud-app.yml` with a single composite action `.github/actions/cloud-app/action.yml` that the caller invokes as one step in its own gated job.

**Architecture:** All deploy phases (parse → bootstrap dispatch → build → resolve → secrets → terraform) run as steps in the caller's single job. A `uses:`'d remote action is fetched to `${{ github.action_path }}`, so `engine/`, `terraform/`, `environments/`, `.github/scripts/` are reachable with **no control-repo checkout**. App secrets are enumerated explicitly by the caller as `NAME=value` lines.

**Tech Stack:** GitHub Actions composite actions, Python engine (`python -m cloudapp`), Azure CLI / azurerm Terraform, pytest.

## Global Constraints

- Pinned action SHAs (reuse existing): checkout `11d5960a326750d5838078e36cf38b85af677262` (v4); `azure/login` `a457da9ea143d694b1b9c7c869ebb04ebe844ef5` (v2); `actions/create-github-app-token` `d72941d797fd3113feb6b93fd0dec494b13a2547` (v1).
- `cloud-app` action lives at `.github/actions/cloud-app/` — same directory depth as the old sub-actions, so `${{ github.action_path }}/../../../engine`, `/../../../terraform`, `/../../../environments`, `/../../scripts` all resolve.
- Engine stays unchanged except the secrets input shim (Task 1).
- Trust repo untouched: `.github/workflows/bootstrap.yml`, `.github/actions/deploy-stack/`.
- `app-secrets` format: newline-delimited `NAME=value`, split on the **first** `=`; single-line values only.
- Python: engine runs on the repo's existing pinned deps (`engine/requirements.txt` / `requirements-dev.txt`); ruff config in `engine/ruff.toml`.

---

### Task 1: Engine — `app-secrets` pair parser + wire into `sync-secrets`

Adds a pure parser turning enumerated `NAME=value` app-secrets into the dict `secrets.sync()` already consumes, and makes `cmd_sync_secrets` prefer it (env `APP_SECRETS`) over the legacy `ALL_SECRETS` JSON blob. Engine-level so it is unit-testable, not buried in bash.

**Files:**

- Modify: `engine/cloudapp/secrets.py` (add `parse_pairs`, `load_secrets`)
- Modify: `engine/cloudapp/cli.py:76-86` (`cmd_sync_secrets` uses `load_secrets`)
- Test: `engine/tests/py/test_secrets.py`

**Interfaces:**

- Produces: `secrets.parse_pairs(text: str) -> dict[str, str]` — first-`=` split, blank lines skipped, a line without `=` or with an empty name raises `SyncError`.
- Produces: `secrets.load_secrets(env: Mapping[str, str]) -> dict[str, str]` — returns `parse_pairs(env["APP_SECRETS"])` when `APP_SECRETS` is set and non-blank, else `json.loads(env.get("ALL_SECRETS") or "{}")`.
- Consumes (unchanged): `secrets.sync(tool, vault, all_secrets, run, require_vault=...)`.

- [ ] **Step 1: Write the failing tests**

Add to `engine/tests/py/test_secrets.py`:

```python
import pytest

from cloudapp import secrets


def test_parse_pairs_basic():
    assert secrets.parse_pairs("STRIPE_KEY=sk_live_123") == {"STRIPE_KEY": "sk_live_123"}


def test_parse_pairs_splits_on_first_equals():
    # base64 / values that themselves contain '='
    assert secrets.parse_pairs("TOKEN=YWJjПw==") == {"TOKEN": "YWJjПw=="}


def test_parse_pairs_multiple_and_blank_lines():
    text = "A=1\n\n  \nB=two=parts\n"
    assert secrets.parse_pairs(text) == {"A": "1", "B": "two=parts"}


def test_parse_pairs_missing_equals_raises():
    with pytest.raises(secrets.SyncError):
        secrets.parse_pairs("NOT_A_PAIR")


def test_parse_pairs_empty_name_raises():
    with pytest.raises(secrets.SyncError):
        secrets.parse_pairs("=value")


def test_load_secrets_prefers_app_secrets_pairs():
    env = {"APP_SECRETS": "STRIPE_KEY=sk_1", "ALL_SECRETS": '{"STRIPE_KEY":"ignored"}'}
    assert secrets.load_secrets(env) == {"STRIPE_KEY": "sk_1"}


def test_load_secrets_falls_back_to_all_secrets_json():
    env = {"ALL_SECRETS": '{"STRIPE_KEY":"sk_2"}'}
    assert secrets.load_secrets(env) == {"STRIPE_KEY": "sk_2"}


def test_load_secrets_blank_app_secrets_falls_back():
    env = {"APP_SECRETS": "   \n", "ALL_SECRETS": '{"X":"y"}'}
    assert secrets.load_secrets(env) == {"X": "y"}


def test_load_secrets_empty_returns_empty_dict():
    assert secrets.load_secrets({}) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd engine && python -m pytest tests/py/test_secrets.py -k "parse_pairs or load_secrets" -v`
Expected: FAIL — `AttributeError: module 'cloudapp.secrets' has no attribute 'parse_pairs'`.

- [ ] **Step 3: Implement `parse_pairs` and `load_secrets`**

At the top of `engine/cloudapp/secrets.py`, add `import json` beside the existing imports:

```python
import json
import re
import time
```

Append these functions to `engine/cloudapp/secrets.py` (after `sync`):

```python
def parse_pairs(text):
    """Parse newline-delimited NAME=value app secrets into a dict.

    Splits each non-blank line on the first '=' so values may contain '='.
    Single-line values only (the enumerated caller format cannot express a
    multiline secret). A line without '=' or with an empty name is an error.
    """
    result = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise SyncError(f"malformed app-secrets line {lineno}: expected NAME=value")
        name, value = line.split("=", 1)
        name = name.strip()
        if not name:
            raise SyncError(f"malformed app-secrets line {lineno}: empty secret name")
        result[name] = value
    return result


def load_secrets(env):
    """Deploy-time secret map from the environment.

    Prefers APP_SECRETS (enumerated NAME=value pairs the caller passes to the
    cloud-app action); falls back to the legacy ALL_SECRETS JSON blob.
    """
    pairs = env.get("APP_SECRETS")
    if pairs is not None and pairs.strip():
        return parse_pairs(pairs)
    return json.loads(env.get("ALL_SECRETS") or "{}")
```

- [ ] **Step 4: Wire `cmd_sync_secrets` to use `load_secrets`**

In `engine/cloudapp/cli.py`, change `cmd_sync_secrets` (line ~78):

```python
def cmd_sync_secrets(args):
    tool = _load_json(args.tool_json)
    all_secrets = secrets.load_secrets(os.environ)
    outputs = secrets.sync(
        tool,
        args.keyvault_name,
        all_secrets,
        runner.run,
        require_vault=args.require_vault,
    )
    gha.write_outputs(outputs)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd engine && python -m pytest tests/py/test_secrets.py -v`
Expected: PASS (new tests + existing secrets tests).

- [ ] **Step 6: Lint + full engine suite**

Run: `cd engine && ruff check . && python -m pytest -q`
Expected: no lint errors; full suite green.

- [ ] **Step 7: Commit**

```bash
git add engine/cloudapp/secrets.py engine/cloudapp/cli.py engine/tests/py/test_secrets.py
git commit -m "feat(secrets): accept enumerated APP_SECRETS pairs for sync"
```

---

### Task 2: Create the `cloud-app` composite action

The single entrypoint. Inlines the six removed sub-actions' `python -m cloudapp ...` calls plus the build/deploy/bootstrap logic from the old reusable workflow, all `${{ github.action_path }}`-relative. No checkouts, no artifacts.

**Files:**

- Create: `.github/actions/cloud-app/action.yml`

**Interfaces:**

- Consumes: engine subcommands `parse-manifest`, `docker-build`, `resolve-config`, `sync-secrets`, `terraform-deploy`; `.github/scripts/dispatch_and_wait.py`; `secrets.load_secrets` via `APP_SECRETS` env (Task 1).
- Produces: action outputs `name`, `resource_group`, `summary` (for the caller to consume if desired).

- [ ] **Step 1: Write the action file**

Create `.github/actions/cloud-app/action.yml`:

```yaml
name: cloud-app
description: >-
  Deploy one environment of a cloud-app stack. Dispatches the control repo's
  bootstrap (Phase 1: RG + plan/apply identities federated to this repo), then
  runs the resource deploy under those RG-scoped identities (Phase 2). Invoke
  as a step in a job that sets `environment:` — the OIDC subject the RG-scoped
  identities trust.
inputs:
  env:
    description: Target environment to deploy (must be declared in the manifest)
    required: true
  manifest:
    description: Path to the cloud-app manifest in the caller repo
    default: .cloud-app.yml
  plan_only:
    description: Plan without applying
    default: "false"
  app-id:
    description: GitHub App id used to dispatch the control repo bootstrap
    required: true
  app-private-key:
    description: GitHub App private key (.pem contents)
    required: true
  app-secrets:
    description: >-
      Newline-delimited NAME=value app secrets to sync to Key Vault. Enumerate
      exactly the names your manifest `secrets:` list declares. Single-line
      values only.
    default: ""
  control-repo:
    description: Control repo name that holds bootstrap.yml
    default: cloud-app
  control-ref:
    description: Ref of the control repo to run bootstrap.yml from
    default: main
outputs:
  name:
    description: Resolved stack name (manifest name)
    value: ${{ steps.parse.outputs.name }}
  resource_group:
    description: Resource group created by the bootstrap
    value: ${{ steps.bootstrap.outputs.resource_group }}
  summary:
    description: One-line terraform plan/apply summary
    value: ${{ steps.deploy.outputs.summary }}
runs:
  using: composite
  steps:
    - name: Install engine deps
      shell: bash
      run: pip install -q -r "${{ github.action_path }}/../../../engine/requirements.txt"

    - name: Parse manifest
      id: parse
      shell: bash
      run: >-
        PYTHONPATH="${{ github.action_path }}/../../../engine"
        python3 -m cloudapp parse-manifest
        --manifest "${{ inputs.manifest }}"
        --output-dir .cloud-app
        --app-root "."

    - name: Validate target environment is declared
      shell: bash
      env:
        ENVIRONMENTS: ${{ steps.parse.outputs.environments }}
        ENV: ${{ inputs.env }}
      run: |
        if ! echo "$ENVIRONMENTS" | jq -e --arg e "$ENV" 'index($e)' > /dev/null; then
          echo "::error::environment '$ENV' is not declared in the manifest ($(echo "$ENVIRONMENTS" | jq -r 'join(", ")'))"
          exit 1
        fi

    - name: Generate control-repo App token
      id: token
      uses: actions/create-github-app-token@d72941d797fd3113feb6b93fd0dec494b13a2547 # v1
      with:
        app-id: ${{ inputs.app-id }}
        private-key: ${{ inputs.app-private-key }}
        owner: ${{ github.repository_owner }}
        repositories: ${{ inputs.control-repo }}

    - name: Bootstrap dispatch (Phase 1)
      id: bootstrap
      shell: bash
      env:
        GH_TOKEN: ${{ steps.token.outputs.token }}
        TARGET_OWNER: ${{ github.repository_owner }}
        TARGET_REPO: ${{ inputs.control-repo }}
        TARGET_WORKFLOW: bootstrap.yml
        TARGET_BRANCH: ${{ inputs.control-ref }}
        INPUT_REPO: ${{ github.event.repository.name }}
        INPUT_MANIFEST: ${{ inputs.manifest }}
        INPUT_STACK_NAME: ${{ steps.parse.outputs.name }}
        INPUT_BRANCH: ${{ github.ref_name }}
        INPUT_ENV: ${{ inputs.env }}
        INPUT_PLAN_ONLY: ${{ inputs.plan_only }}
      run: python "${{ github.action_path }}/../../scripts/dispatch_and_wait.py"

    - name: Read platform config
      id: platform
      shell: bash
      env:
        DEPLOY_ENV: ${{ inputs.env }}
        TOOL_NAME: ${{ steps.parse.outputs.name }}
      run: |
        FILE="${{ github.action_path }}/../../../environments/$DEPLOY_ENV.yml"
        if [ ! -f "$FILE" ]; then
          echo "::error::no platform config for environment '$DEPLOY_ENV' ($FILE missing)"
          exit 1
        fi
        {
          echo "file=$FILE"
          echo "registry=$(yq '.acr.login_server' "$FILE")"
          echo "client_id=$(yq '.deploy.client_id' "$FILE")"
          echo "tenant_id=$(yq '.tenant_id' "$FILE")"
          echo "subscription_id=$(yq '.subscription_id' "$FILE")"
          PREFIX=$(yq '.naming_prefix // ""' "$FILE")
          KV=$(python3 -c "import sys; n = ('kv-' + sys.argv[1] + sys.argv[2] + '-' + sys.argv[3])[:24]; print(n[:-1] if n.endswith('-') else n)" "$PREFIX" "$TOOL_NAME" "$DEPLOY_ENV")
          echo "keyvault=$KV"
        } >> "$GITHUB_OUTPUT"

    # Build: push under the apply identity (repo-scoped ACR push). Skipped for
    # non-docker stacks and plan-only runs.
    - name: Azure login (build, apply identity)
      if: ${{ steps.parse.outputs.docker == 'true' && inputs.plan_only == 'false' }}
      uses: azure/login@a457da9ea143d694b1b9c7c869ebb04ebe844ef5 # v2
      with:
        client-id: ${{ steps.bootstrap.outputs.apply_client_id }}
        tenant-id: ${{ steps.platform.outputs.tenant_id }}
        subscription-id: ${{ steps.platform.outputs.subscription_id }}

    - name: Build and push image
      id: build
      if: ${{ steps.parse.outputs.docker == 'true' && inputs.plan_only == 'false' }}
      shell: bash
      env:
        DEPLOY_ENV: ${{ inputs.env }}
      run: >-
        PYTHONPATH="${{ github.action_path }}/../../../engine"
        python3 -m cloudapp docker-build
        --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
        --tool-name "${{ steps.parse.outputs.name }}"
        --registry "${{ steps.platform.outputs.registry }}"
        --git-sha "${{ github.sha }}"

    # Deploy: log in as the RG-scoped identity bootstrap federated to this repo —
    # plan (Reader) for plan-only, apply (Contributor) otherwise.
    - name: Azure login (deploy)
      uses: azure/login@a457da9ea143d694b1b9c7c869ebb04ebe844ef5 # v2
      with:
        client-id: ${{ inputs.plan_only == 'true' && steps.bootstrap.outputs.plan_client_id || steps.bootstrap.outputs.apply_client_id }}
        tenant-id: ${{ steps.platform.outputs.tenant_id }}
        subscription-id: ${{ steps.platform.outputs.subscription_id }}

    - name: Resolve config
      id: resolve
      shell: bash
      env:
        DEPLOY_ENV: ${{ inputs.env }}
      run: >-
        PYTHONPATH="${{ github.action_path }}/../../../engine"
        python3 -m cloudapp resolve-config
        --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
        --platform-file "${{ steps.platform.outputs.file }}"
        --environment "$DEPLOY_ENV"
        --out-file tfvars.json

    - name: Sync secrets
      id: secrets
      if: ${{ inputs.plan_only == 'false' }}
      shell: bash
      env:
        DEPLOY_ENV: ${{ inputs.env }}
        APP_SECRETS: ${{ inputs.app-secrets }}
      run: >-
        PYTHONPATH="${{ github.action_path }}/../../../engine"
        python3 -m cloudapp sync-secrets
        --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
        --keyvault-name "${{ steps.platform.outputs.keyvault }}"

    - name: First-deploy targeted apply (key vault before secrets)
      if: ${{ inputs.plan_only == 'false' && steps.secrets.outputs.vault-exists == 'false' }}
      shell: bash
      env:
        DEPLOY_ENV: ${{ inputs.env }}
        TF_IN_AUTOMATION: "true"
        IMAGE_TAGS: ${{ steps.build.outputs.image-tags || '{}' }}
        TARGETS: module.keyvault
      run: >-
        PYTHONPATH="${{ github.action_path }}/../../../engine"
        python3 -m cloudapp terraform-deploy
        --terraform-dir "${{ github.action_path }}/../../../terraform/azure"
        --tfvars-file tfvars.json
        --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
        --tool-name "${{ steps.parse.outputs.name }}"
        --environment "$DEPLOY_ENV"
        --platform-file "${{ steps.platform.outputs.file }}"
        --image-tags "$IMAGE_TAGS"
        --targets "$TARGETS"
        --stack main

    - name: Sync secrets after vault creation
      if: ${{ inputs.plan_only == 'false' && steps.secrets.outputs.vault-exists == 'false' }}
      shell: bash
      env:
        DEPLOY_ENV: ${{ inputs.env }}
        APP_SECRETS: ${{ inputs.app-secrets }}
      run: >-
        PYTHONPATH="${{ github.action_path }}/../../../engine"
        python3 -m cloudapp sync-secrets
        --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
        --keyvault-name "${{ steps.platform.outputs.keyvault }}"
        --require-vault

    - name: Terraform deploy
      id: deploy
      shell: bash
      env:
        DEPLOY_ENV: ${{ inputs.env }}
        TF_IN_AUTOMATION: "true"
        IMAGE_TAGS: ${{ steps.build.outputs.image-tags || '{}' }}
      run: >-
        PYTHONPATH="${{ github.action_path }}/../../../engine"
        python3 -m cloudapp terraform-deploy
        --terraform-dir "${{ github.action_path }}/../../../terraform/azure"
        --tfvars-file tfvars.json
        --tool-json ".cloud-app/tool.$DEPLOY_ENV.json"
        --tool-name "${{ steps.parse.outputs.name }}"
        --environment "$DEPLOY_ENV"
        --platform-file "${{ steps.platform.outputs.file }}"
        --image-tags "$IMAGE_TAGS"
        --targets ""
        --stack main
        ${{ inputs.plan_only == 'true' && '--plan-only' || '' }}

    - name: Write summary
      shell: bash
      run: echo "### ${{ steps.deploy.outputs.summary }}" >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 2: Validate the action YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/actions/cloud-app/action.yml')); print('parse OK')"`
Expected: `parse OK`

- [ ] **Step 3: Lint with actionlint if available**

Run: `command -v actionlint >/dev/null && actionlint .github/actions/cloud-app/action.yml || echo "actionlint not installed — skip"`
Expected: no errors, or the skip message.

- [ ] **Step 4: Commit**

```bash
git add .github/actions/cloud-app/action.yml
git commit -m "feat(cloud-app): composite action replacing the reusable workflow"
```

---

### Task 3: Rewrite the sample caller workflow

Turn the sample from a reusable-workflow caller into a full workflow: own job, `environment:` gate, explicit `app-secrets`, one caller checkout.

**Files:**

- Modify: `samples/caller-app/.github/workflows/cloud-app.yml`

**Interfaces:**

- Consumes: `vgmello/cloud-app/.github/actions/cloud-app@main` (Task 2), with inputs `env`, `plan_only`, `app-id`, `app-private-key`, `app-secrets`.

- [ ] **Step 1: Replace the sample workflow**

Overwrite `samples/caller-app/.github/workflows/cloud-app.yml`:

```yaml
name: Cloud App

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:
    inputs:
      environment:
        description: Target environment
        type: choice
        options: [dev, staging, prod]
        default: dev

permissions:
  contents: read
  id-token: write

concurrency:
  group: cloud-app-${{ github.repository }}-${{ inputs.environment || 'dev' }}-${{ github.event_name == 'pull_request' && 'plan' || 'apply' }}
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    # The approval gate lives here now — the OIDC subject the RG-scoped plan/apply
    # identities trust is repo:<this>:environment:<env>.
    environment: ${{ inputs.environment || 'dev' }}
    steps:
      # Caller checkout: the action reads the manifest and the Dockerfile/context
      # from this repo.
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4

      - uses: vgmello/cloud-app/.github/actions/cloud-app@main
        with:
          env: ${{ inputs.environment || 'dev' }}
          plan_only: ${{ github.event_name == 'pull_request' }}
          app-id: ${{ secrets.APP_ID }}
          app-private-key: ${{ secrets.APP_PRIVATE_KEY }}
          # Enumerate exactly the names your manifest `secrets:` list declares.
          app-secrets: |
            STRIPE_KEY=${{ secrets.STRIPE_KEY }}
```

- [ ] **Step 2: Validate it parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('samples/caller-app/.github/workflows/cloud-app.yml')); print('parse OK')"`
Expected: `parse OK`

- [ ] **Step 3: Commit**

```bash
git add samples/caller-app/.github/workflows/cloud-app.yml
git commit -m "docs(sample): caller workflow calls the cloud-app action"
```

---

### Task 4: Remove the reusable workflow and absorbed sub-actions

Delete the old entrypoint and the six sub-actions whose logic Task 2 inlined. Verify nothing else references them.

**Files:**

- Delete: `.github/workflows/cloud-app.yml`
- Delete: `.github/actions/parse-manifest/`, `.github/actions/docker-build/`, `.github/actions/resolve-config/`, `.github/actions/sync-secrets/`, `.github/actions/terraform-deploy/`, `.github/actions/cloudapp-dispatch-workflow/`

- [ ] **Step 1: Confirm no remaining references**

Run:

```bash
grep -rn "actions/parse-manifest\|actions/docker-build\|actions/resolve-config\|actions/sync-secrets\|actions/terraform-deploy\|actions/cloudapp-dispatch-workflow\|workflows/cloud-app.yml" .github/ samples/ README.md docs/ registries/ || echo "no references — clear"
```

Expected: `no references — clear` (the sample now uses `actions/cloud-app`; `bootstrap.yml`/`deploy-stack` are untouched and reference neither).

- [ ] **Step 2: Delete the files**

Run:

```bash
git rm .github/workflows/cloud-app.yml
git rm -r .github/actions/parse-manifest .github/actions/docker-build .github/actions/resolve-config .github/actions/sync-secrets .github/actions/terraform-deploy .github/actions/cloudapp-dispatch-workflow
```

- [ ] **Step 3: Verify deploy-stack + bootstrap.yml still intact**

Run: `ls .github/actions/ && test -f .github/workflows/bootstrap.yml && echo "control side intact"`
Expected: lists `cloud-app` and `deploy-stack` (only); `control side intact`.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(cloud-app): remove reusable workflow and absorbed sub-actions"
```

---

### Task 5: Update docs for the action model

Fix every doc that still shows the reusable-workflow form (`uses: .../cloud-app.yml` + `secrets: inherit`) to the action-step form.

**Files:**

- Modify: `README.md` (caller example ~line 36-43)
- Modify: `docs/usage.md` (caller example ~line 35-43)
- Modify: `registries/README.md` (caller-usage block ~line 43-52)
- Modify: `samples/caller-app/README.md` (file table + prose)

**Interfaces:** none (documentation).

- [ ] **Step 1: Update `README.md` caller snippet**

Replace the `jobs:` block in the quick-start example with the action-step form (own job, `environment:`, explicit `app-secrets`), matching `samples/caller-app/.github/workflows/cloud-app.yml`:

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment || 'dev' }}
    steps:
      - uses: actions/checkout@v4
      - uses: vgmello/cloud-app/.github/actions/cloud-app@v1
        with:
          env: dev
          plan_only: ${{ github.event_name == 'pull_request' }}
          app-id: ${{ secrets.APP_ID }}
          app-private-key: ${{ secrets.APP_PRIVATE_KEY }}
          app-secrets: |
            STRIPE_KEY=${{ secrets.STRIPE_KEY }}
```

- [ ] **Step 2: Update `docs/usage.md` caller snippet**

Apply the same action-step form. Remove any `secrets: inherit` and `repo_ref`/`stack_name` lines. Add a short note: "App secrets are enumerated explicitly under `app-secrets` — one `NAME=value` per line, matching the manifest `secrets:` list."

- [ ] **Step 3: Update `registries/README.md` caller-usage block**

Replace the `uses: <owner>/cloud-app/.github/workflows/cloud-app.yml@main` + `with: {env, ...}` block with the action-step form (own job + `environment:` + `uses: <owner>/cloud-app/.github/actions/cloud-app@main`). Keep the registry file-format section (`stack_name: cloud-app`) unchanged — that is the lock-file schema, not a caller input.

- [ ] **Step 4: Update `samples/caller-app/README.md`**

In the two-file table, the workflow row already reads `.github/workflows/cloud-app.yml`; ensure the "How it works" prose describes: caller's own workflow runs `cloud-app` **action** in one gated job; it dispatches the control repo bootstrap, then deploys under the returned RG identities. Add a bullet under "To use in your own app repo": "Enumerate your manifest `secrets:` under the action's `app-secrets:` input, one `NAME=value` per line."

- [ ] **Step 5: Verify no reusable-workflow references remain in docs**

Run:

```bash
grep -rn "cloud-app.yml@\|secrets: inherit\|stack_name:" README.md docs/usage.md registries/README.md samples/caller-app/ | grep -v "registries/README.md.*stack_name: cloud-app"
```

Expected: no output (the only surviving `stack_name:` is the registry lock-file schema line).

- [ ] **Step 6: Commit**

```bash
git add README.md docs/usage.md registries/README.md samples/caller-app/README.md
git commit -m "docs: switch caller examples to the cloud-app action"
```

---

## Self-Review

**Spec coverage:**

- Composite action, single gated job, zero control-repo checkouts → Task 2 + Task 3. ✓
- Inline sub-actions via `github.action_path` → Task 2. ✓
- Remove reusable workflow + six sub-actions → Task 4. ✓
- app-secrets explicit enumerate, first-`=` split, single-line, missing-name fail-fast → Task 1 (parser + `secrets.sync` already raises on missing manifest name). ✓
- OIDC env-subject consolidation (incidental fix) → realized by the single `environment:`-gated job in Task 3; action logins in Task 2 present it. ✓
- Trust repo untouched → asserted in Task 4 Step 3. ✓
- Docs updated → Task 5. ✓

**Placeholder scan:** No TBD/TODO; every code/YAML block is complete and verbatim. `@v1`/`@main`/`<owner>` are intentional example refs.

**Type consistency:** `parse_pairs`/`load_secrets` signatures identical across Task 1 definition and Task 2 consumption (`APP_SECRETS` env). Step output names (`steps.parse.outputs.name/docker/environments`, `steps.bootstrap.outputs.{plan_client_id,apply_client_id,resource_group}`, `steps.platform.outputs.*`, `steps.build.outputs.image-tags`, `steps.secrets.outputs.vault-exists`, `steps.deploy.outputs.summary`) match the engine subcommands' documented outputs and the old workflow's usage.

**Note on live validation:** GitHub Actions execution can't be run locally; Tasks 2-5 verify via YAML parse + `actionlint` + reference greps. Full end-to-end validation remains gated on a real deploy, consistent with the platform's "wired, not yet live-validated" status.
