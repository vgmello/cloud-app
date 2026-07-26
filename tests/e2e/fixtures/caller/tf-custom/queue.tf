# Caller-supplied Terraform. Copied verbatim into the platform's `custom`
# child module at deploy time — see docs/usage.md#caller-supplied-terraform.
# Runs in the main stack, so it applies under the tool's RG-scoped apply
# identity: everything here is confined to var.resource_group_name.
#
# `random` is declared under `terraform.providers` in ../cloud-app.yml; it's
# used here to keep the storage account name globally unique.

resource "random_string" "queue_suffix" {
  length  = 4
  special = false
  upper   = false
}

resource "azurerm_storage_account" "custom" {
  name                     = "stqueue${random_string.queue_suffix.result}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_storage_queue" "jobs" {
  name                 = "jobs"
  storage_account_name = azurerm_storage_account.custom.name
}

# Lets the "api" app read from the queue using its own managed identity —
# no connection string needed.
resource "azurerm_role_assignment" "app_can_read" {
  scope                = azurerm_storage_account.custom.id
  role_definition_name = "Storage Queue Data Reader"
  principal_id         = var.app_identity_principal_ids["api"]
}
