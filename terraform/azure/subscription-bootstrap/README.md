# Subscription bootstrap (run once per subscription + environment)

> **Prerequisite for already-bootstrapped environments.** If this environment
> was bootstrapped before the per-stack state container role
> (`cloudapp-state-container-<env>`) was introduced, re-run
> `subscription-bootstrap` to pick up that role **before** the next stack
> bootstrap runs. Otherwise creating the per-stack state container fails with
> an authorization error.

A subscription **Owner** runs this stack one time per environment. It creates
the `cloudapp-bootstrap` custom role, the shared `id-cloudapp-bootstrap-<env>`
identity, its role assignment, a federated credential trusting the trusted
repo's `environment:<env>` subject, and (when a state account is given) the
bootstrap identity's Storage Blob Data Contributor grant on the tfstate
container so it can store its own `bootstrap.tfstate`.

```bash
terraform -chdir=terraform/azure/subscription-bootstrap init
terraform -chdir=terraform/azure/subscription-bootstrap apply \
  -var subscription_id=<sub> -var location=eastus2 \
  -var environment=dev -var trusted_repo=vgmello/cloud-app \
  -var state_account_id=/subscriptions/<sub>/resourceGroups/rg-tfstate/providers/Microsoft.Storage/storageAccounts/<acct> \
  -var state_container=tfstate
```

Record `bootstrap_identity_client_id` in `environments/<env>.yml` as
`bootstrap_identity_client_id`. In delegated mode `trusted_repo` is the central
deploy repo; in self mode it is the app repo.
