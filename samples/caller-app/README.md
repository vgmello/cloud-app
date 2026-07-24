# Sample caller app

A minimal example of an **app repo** that deploys through the control plane
without owning any Terraform, Azure identity, or deploy credentials.

Two files are all an app repo needs:

| File                              | Purpose                                                       |
| --------------------------------- | ------------------------------------------------------------- |
| `.cloud-app.yml`                  | The stack manifest — what to deploy (apps, database, secrets) |
| `.github/workflows/cloud-app.yml` | Runs the `cloud-app` action in this repo's own gated job      |

## How it works

1. Merge to `main` (or run the workflow manually and pick an environment).
2. This repo's own `cloud-app.yml` workflow runs the `cloud-app` action as a
   step in its single, environment-gated job. The action dispatches the
   control repo (`vgmello/cloud-app`) to bootstrap the stack, which triggers
   the control repo's deploy workflow under **its** identity — this repo
   never holds deploy-capable credentials.
3. The control repo's stack-lock registry
   (`registries/<env>/orders-api.yml`) authorizes this repo. First deploy
   claims the stack (trust-on-first-use); later callers must be added to
   `allowed_repos`.
4. The bootstrap returns the RG-scoped plan/apply identities, and the action
   deploys under them: `parse -> resolve -> terraform apply`, reporting the
   result back to this workflow.

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
