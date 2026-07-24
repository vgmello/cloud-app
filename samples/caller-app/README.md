# Sample caller app

A minimal example of an **app repo** that deploys through the control plane
without owning any Terraform, Azure identity, or deploy credentials.

Two files are all an app repo needs:

| File                           | Purpose                                                         |
| ------------------------------ | --------------------------------------------------------------- |
| `.cloud-app.yml`               | The stack manifest — what to deploy (apps, database, secrets)   |
| `.github/workflows/deploy.yml` | Dispatches the deploy to the control repo (`vgmello/cloud-app`) |

## How it works

1. Merge to `main` (or run the workflow manually and pick an environment).
2. the reusable `cloud-app.yml` (their `deploy.yml` calls it) dispatches the control repo, which triggers
   the control repo's deploy workflow under **its** identity — this repo never
   holds deploy-capable credentials.
3. The control repo's stack-lock registry
   (`registries/<env>/orders-api.yml`) authorizes this repo. First deploy
   claims the stack (trust-on-first-use); later callers must be added to
   `allowed_repos`.
4. The control plane runs `parse -> resolve -> terraform apply` and reports the
   result back to this workflow.

## To use in your own app repo

- Copy both files to your repo root / `.github/workflows/`.
- Set the manifest `name:` and the workflow `stack-name:` to your stack (they
  must match).
- Add repo secrets `APP_ID` and `APP_PRIVATE_KEY` (the GitHub App installed on
  the control repo); `secrets: inherit` passes them to the reusable workflow.

> This folder is a template. Its `.github/workflows/deploy.yml` is inert here —
> GitHub only runs workflows from a repo's own root `.github/workflows/`.
