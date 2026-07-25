provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

locals {
  scope = "/subscriptions/${var.subscription_id}"
}

resource "azurerm_role_definition" "bootstrap" {
  name        = "cloudapp-bootstrap"
  scope       = local.scope
  description = "Create resource groups, user-assigned identities, and role assignments only"

  permissions {
    actions = [
      "Microsoft.Resources/subscriptions/resourceGroups/read",
      "Microsoft.Resources/subscriptions/resourceGroups/write",
      "Microsoft.ManagedIdentity/userAssignedIdentities/read",
      "Microsoft.ManagedIdentity/userAssignedIdentities/write",
      "Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials/read",
      "Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials/write",
      "Microsoft.Authorization/roleAssignments/read",
      "Microsoft.Authorization/roleAssignments/write",
    ]
    not_actions = []
  }

  assignable_scopes = [local.scope]
}

resource "azurerm_resource_group" "identities" {
  name     = "rg-cloudapp-identities-${var.environment}"
  location = var.location
}

resource "azurerm_user_assigned_identity" "bootstrap" {
  name                = "id-cloudapp-bootstrap-${var.environment}"
  location            = var.location
  resource_group_name = azurerm_resource_group.identities.name
}

# Built-in role definition IDs the bootstrap identity is allowed to assign. An
# identity with roleAssignments/write at subscription scope can otherwise assign
# ANY role (including Owner) to any principal — the classic Azure escalation.
# This ABAC condition constrains its assignments to the deploy roles only.
locals {
  assignable_roles = {
    reader                        = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
    contributor                   = "b24988ac-6180-42a0-ab88-20f7382dd24c"
    storage_blob_data_reader      = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"
    storage_blob_data_contributor = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
    key_vault_reader              = "21090545-7ca7-4776-b22c-e363652d74d2"
    # ABAC-enabled ACR role: lets the per-tool bootstrap grant repo-scoped push.
    acr_repository_writer = "2a1e307c-b015-4ebd-883e-5b7698a07328"
  }
  assignable_role_guids = join(", ", [for g in values(local.assignable_roles) : format("'%s'", g)])
}

resource "azurerm_role_assignment" "bootstrap" {
  scope              = local.scope
  role_definition_id = azurerm_role_definition.bootstrap.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.bootstrap.principal_id

  condition_version = "2.0"
  condition         = <<-COND
    (
     (
      !(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})
     )
     OR
     (
      @Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${local.assignable_role_guids}}
     )
    )
  COND
}

resource "azurerm_federated_identity_credential" "bootstrap" {
  name      = "gha-${var.environment}"
  parent_id = azurerm_user_assigned_identity.bootstrap.id
  audience  = ["api://AzureADTokenExchange"]
  issuer    = "https://token.actions.githubusercontent.com"
  subject   = "repo:${var.trusted_repo}:environment:${var.environment}"
}

# The bootstrap identity stores its own bootstrap.tfstate in the state container,
# so it needs data-plane write there (outside the tool RGs it manages). Scoped to
# the container when known, else the account. Skipped when no state account given.
locals {
  state_scope = (
    var.state_account_id == "" ? "" :
    var.state_container == "" ? var.state_account_id :
    "${var.state_account_id}/blobServices/default/containers/${var.state_container}"
  )
}

resource "azurerm_role_assignment" "bootstrap_state" {
  count                = local.state_scope == "" ? 0 : 1
  scope                = local.state_scope
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.bootstrap.principal_id
}

# Container CRUD for the bootstrap identity, in its own role assigned ONLY at
# the state account. Kept out of the cloudapp-bootstrap role because that role
# is assigned at subscription scope, where these actions would reach every
# storage account in the subscription (app workload + function backing stores).
resource "azurerm_role_definition" "state_container" {
  count       = var.state_account_id == "" ? 0 : 1
  name        = "cloudapp-state-container-${var.environment}"
  scope       = local.scope
  description = "Grants container CRUD on the state account only"

  permissions {
    actions = [
      "Microsoft.Storage/storageAccounts/read",
      "Microsoft.Storage/storageAccounts/blobServices/containers/read",
      "Microsoft.Storage/storageAccounts/blobServices/containers/write",
    ]
    not_actions = []
  }

  assignable_scopes = [local.scope]
}

resource "azurerm_role_assignment" "state_container" {
  count              = var.state_account_id == "" ? 0 : 1
  scope              = var.state_account_id
  role_definition_id = azurerm_role_definition.state_container[0].role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.bootstrap.principal_id
}
