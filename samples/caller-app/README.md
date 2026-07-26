# Sample caller app

A minimal example of an **app repo** that deploys through the control plane
without owning any Terraform, Azure identity, or deploy credentials.

Two files are all an app repo needs:

| File                              | Purpose                                                       |
| --------------------------------- | ------------------------------------------------------------- |
| `cloud-app.yml`                   | The stack manifest — what to deploy (apps, database, secrets) |
| `.github/workflows/cloud-app.yml` | Runs the `cloud-app` action in this repo's own gated job      |

## How it works

1. Merge to `main` (or run the workflow manually and pick an environment).
2. This repo's own `cloud-app.yml` workflow runs the `cloud-app` action as a
   step in its single, environment-gated job. The action dispatches the
   control repo (`vgmello/cloud-app`) to run the bootstrap under the control
   repo's subscription-scoped identity — creating the resource group and the
   RG-scoped plan/apply identities federated to this repo. This repo never
   holds subscription-scoped credentials.
3. The control repo's stack-lock registry
   (`registries/<env>/orders-api.yml`) authorizes this repo. First deploy
   claims the stack (trust-on-first-use); later callers must be added to
   `allowed_repos`.
4. The bootstrap returns the RG-scoped plan/apply identities, and the action
   deploys under them: `parse -> resolve -> terraform apply`, reporting the
   result back to this workflow.

On an unchanged manifest (a code-only change), the action skips Terraform and
rolls the freshly built image directly onto the existing container apps /
functions (`az containerapp update` / `az functionapp config container set`) —
fast, no plan/apply. A manifest change, first deploy, manual dispatch, or
`always_run_terraform: true` runs the full Terraform plan+apply instead. Static
sites are not image-rotated, and a rotated secret with no new commit is picked
up on the next revision (push a commit or restart the revision to force it).

## When a deploy fails verification

After deploying, the action checks that every container app and function app in
the manifest exists and is healthy, and fails the run if not. Two common causes:

- **A crash-looping image.** The deploy succeeded but the new revision is
  unhealthy — check the container logs for that revision (the error names it).
- **An incomplete stack.** An earlier deploy failed partway, so a resource was
  never created. Re-run the workflow manually with `always_run_terraform: true`
  to force a full Terraform run and finish the stack. Note that a plain manual
  `workflow_dispatch` run already forces a full Terraform run on its own — the
  `always_run_terraform` input exists for callers who want to force that same
  full run from other triggers, such as a normal push where the manifest
  itself did not change.

Set `verify_deploy: false` on the action to skip the check.

## To use in your own app repo

- Copy both files to your repo root / `.github/workflows/`.
- Set the manifest `name:` to your stack — the action resolves the stack name
  from it, so there is nothing to set in the workflow.
- Add repo secrets `APP_ID` and `APP_PRIVATE_KEY` (the GitHub App installed on
  the control repo) and pass them to the action's `app-id` / `app-private-key`
  inputs.
- Enumerate your manifest `secrets:` under the action's `app-secrets:` input,
  one `NAME=value` per line.

> This folder is a template. Its `.github/workflows/cloud-app.yml` is inert here —
> GitHub only runs workflows from a repo's own root `.github/workflows/`.
