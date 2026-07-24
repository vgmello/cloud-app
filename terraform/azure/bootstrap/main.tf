provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

locals {
  rg = "rg-${var.name}-${var.environment}"
}

resource "azurerm_resource_group" "this" {
  name     = local.rg
  location = var.location
}

resource "azurerm_user_assigned_identity" "plan" {
  name                = "id-${var.name}-${var.environment}-plan"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
}

resource "azurerm_user_assigned_identity" "apply" {
  name                = "id-${var.name}-${var.environment}-apply"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
}

# plan identity: read-only across the RG, plus the data-plane reads plan refresh needs
resource "azurerm_role_assignment" "plan_reader" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.plan.principal_id
}

resource "azurerm_role_assignment" "plan_blob" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.plan.principal_id
}

resource "azurerm_role_assignment" "plan_kv" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Key Vault Reader"
  principal_id         = azurerm_user_assigned_identity.plan.principal_id
}

# apply identity: write across the RG
resource "azurerm_role_assignment" "apply_contributor" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.apply.principal_id
}

# apply identity: repo-scoped push to the shared ACR (ABAC-enabled registry).
# The ABAC condition constrains writes to the tool's own repository namespace
# (`<name>/*`), so the caller can push only its own images. Reads are left
# unrestricted. Skipped when acr_id is empty.
resource "azurerm_role_assignment" "apply_acr_push" {
  count                = var.acr_id == "" ? 0 : 1
  scope                = var.acr_id
  role_definition_name = "Container Registry Repository Writer"
  principal_id         = azurerm_user_assigned_identity.apply.principal_id

  condition_version = "2.0"
  condition         = <<-COND
    (
     (
      !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/content/write'})
      AND
      !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/metadata/write'})
     )
     OR
     (
      @Request[Microsoft.ContainerRegistry/registries/repositories:name] StringStartsWithIgnoreCase '${var.name}/'
     )
    )
  COND
}

resource "azurerm_federated_identity_credential" "plan" {
  count     = length(var.plan_subjects)
  name      = "gha-plan-${count.index}"
  parent_id = azurerm_user_assigned_identity.plan.id
  audience  = ["api://AzureADTokenExchange"]
  issuer    = "https://token.actions.githubusercontent.com"
  subject   = var.plan_subjects[count.index]
}

resource "azurerm_federated_identity_credential" "apply" {
  count     = length(var.apply_subjects)
  name      = "gha-apply-${count.index}"
  parent_id = azurerm_user_assigned_identity.apply.id
  audience  = ["api://AzureADTokenExchange"]
  issuer    = "https://token.actions.githubusercontent.com"
  subject   = var.apply_subjects[count.index]
}
