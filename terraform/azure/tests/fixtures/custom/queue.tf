resource "random_pet" "suffix" {
  length = 2
}

resource "azurerm_storage_account" "custom" {
  name                     = substr(replace("stcustom${var.tool_name}${var.environment}", "-", ""), 0, 24)
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}
