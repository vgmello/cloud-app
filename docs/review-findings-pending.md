# Pending review findings

Tracked follow-ups from the security/correctness review. Fixed findings are in
git history; this file lists what is **deliberately deferred** and **why it
matters**, so nothing is silently dropped.

## Architectural — need a design decision before implementing

### #3 — Main stack exceeds the apply identity's permissions

**Why it must be fixed:** the apply identity is only `Contributor` on the tool
resource group. But the main stack does things Contributor cannot do:

- `modules/container-app` and `modules/function` create **role assignments**
  (Contributor cannot write role assignments — needs User Access Administrator
  / Owner, or the assignment must be made by a higher-trust stack).
- `modules/shared/database` and `modules/shared/storage` write **Key Vault
  secrets** (needs a Key Vault data-plane role, not RG Contributor).
- Workloads pull from the **shared ACR** and attach **shared private DNS zones /
  VNet / Container Apps environment** — all outside the tool RG, so RG-scoped
  Contributor does not authorize them.

**Consequence:** a real `terraform apply` fails partway even after state access
works. **Fix direction:** move cross-scope role assignments and shared-resource
joins into the bootstrap/platform stack; grant the apply identity only the
narrow data-plane roles it needs (Key Vault Secrets Officer on its KV, AcrPull
on the shared ACR via ABAC, etc.). Requires a per-resource permission matrix.

### #4 — Bootstrap role can escalate to subscription Contributor

**Why it must be fixed:** the shared bootstrap identity holds
`Microsoft.Authorization/roleAssignments/write` at **subscription scope**. The
ABAC condition restricts only the **role definition id** (to Reader,
Contributor, the Storage Blob roles, Key Vault Reader, ACR Writer) — it does
**not** constrain the assignment **scope** or **target principal**. A compromised
bootstrap workflow can therefore assign itself `Contributor` **at subscription
scope**, defeating the entire least-privilege claim.

**Consequence:** the documented "can only bootstrap per-tool RG identities"
boundary is not real. **Fix direction (a decision):** Azure ABAC can't easily
constrain the target scope of a role assignment, so options are (1)
pre-provision the per-RG identities/assignments out of band, (2) a privileged
broker that validates exact scope/principal/role tuples, or (3) drop
subscription-scope `roleAssignments/write` entirely. Must be threat-modeled and
live-tested against a self-assignment attempt.

### #6 — S3 state backend is structurally non-functional

**Why it must be fixed:** `terraform/azure/versions.tf` hardcodes
`backend "azurerm"`. `terraform init -backend-config` can set values for a
declared backend but **cannot change its type**, so the S3 settings
`backend.py` emits (`bucket`, `region`, `role_arn`) are invalid against an
azurerm backend. The AWS-state path advertised in the docs cannot work.

**Consequence:** anyone selecting `state_backend.type: s3` gets a broken init.
**Fix direction:** separate Terraform roots (or generate the backend block)
per backend type, each with a tested auth flow.

### #8 — PR plans attach a protected environment

**Why it must be fixed:** the deploy job sets `environment: ${{ inputs.env }}`
unconditionally, so a PR "plan" run requires the production approval gate and
can access environment secrets — contradicting the documented "PR plans don't
touch protected gates" behavior, and coupling read-only plans to the apply
approval.

**Consequence:** noisy prod approvals on PRs + wrong OIDC subject for plan.
**Fix direction:** split plan and apply into separate jobs — plan uses the
`pull_request` federated subject with no protected environment; apply uses the
environment subject and the approval gate.

## Partially addressed

### #10 — Bootstrap custom role CRUD (delete actions deferred)

The `federatedIdentityCredentials/read` action was added so `terraform plan` /
refresh / subject-update work. The **delete** actions needed for `destroy` and
identity replacement (`resourceGroups/delete`,
`userAssignedIdentities/delete`, `.../federatedIdentityCredentials/delete`,
`roleAssignments/delete`) are **deferred to #4**: an unguarded
`roleAssignments/delete` widens the same escalation surface, so it must land
together with the anti-escalation redesign, not before.

### #16 — IaC/secret scanners deferred

setup-python (pinned + versioned), ruff, pip-audit, and a checksum-verified
actionlint are wired into CI. **tfsec/Checkov** and **Gitleaks** are deferred:
both flag findings that need triage/allowlisting first (e.g. storage/network
defaults, placeholder GUIDs) and would otherwise break CI on the first run.
Add them behind a triage pass, ideally alongside #11 (network posture).

## Live-only — cannot be validated offline

- **#11 — private-by-default gaps.** Function storage has no network rules /
  private endpoint; the Function App doesn't disable public inbound; Static Web
  Apps are public Free-tier. The global "private by default" claim is not true
  per compute/storage type. Needs explicit public/private inputs + secure
  defaults + network-exposure assertions.
- **#12 — no live/integration tests of the trust boundary.** Python mocks the
  subprocess/network seams; terraform uses mock providers; the lock
  commit/push branch and the real dispatch API behavior are untested. Needs a
  disposable sandbox pipeline (bootstrap → PR plan → apply → no-op apply →
  unauthorized-caller rejection → self-escalation rejection → teardown).
- **#18 — no prod reliability baseline.** Single-zone Postgres, LRS storage, no
  backup/retention/diagnostics/alerts/budgets/locks. Needs production policy
  overlays validated in terraform tests.

## Shipped with a known gap — revisit before the site is promoted

### #19 — landing page states unvalidated trust claims as fact

`site/src/sections/security.ts` and `site/src/sections/escape-hatch.ts` assert
security properties this repo does not yet deliver. Shipped deliberately (the
trust-model work is happening on another branch); recorded here so the copy is
corrected rather than forgotten.

| Page claim                                                                                           | Reality                                                                                                                                                                                     |
| ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "the deploy identity for a stack can only touch that stack's resource group"                         | #3 is open — RG-scoped Contributor cannot write the role assignments, Key Vault secrets, and shared ACR/DNS/VNet joins the main stack needs, so a real apply fails partway.                 |
| "each stack gets its own state container, so one repo can never read or write another's state"       | Wired but never live-validated — see `docs/trust-modes.md` and #12.                                                                                                                         |
| "private endpoints and private DNS for data services … public ingress is an explicit opt-in per app" | True for database, storage, and Key Vault; #11 records that Function App storage and Static Web Apps have no equivalent protection. The page's phrasing does not scope this tightly enough. |
| escape hatch: custom Terraform "confined to your resource group"                                     | Rests on the same apply identity #3 says is insufficient. The provider allowlist half of the claim is accurate (`ALLOWED_PROVIDERS` in `engine/cloudapp/customtf.py`).                      |

Secondary: "OIDC federation, no stored credentials" is accurate for Azure but the
pipeline does hold a long-lived GitHub App private key.

**Fix direction:** once #3, #11, and #12 land, either the claims become true as
written or the copy is reworded to design intent. The page currently carries no
pre-release status line (a deliberate choice) — if the claims are corrected
rather than delivered, restoring that line is the cheaper fix.
