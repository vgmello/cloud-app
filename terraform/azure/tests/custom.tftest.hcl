mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  config     = jsondecode(file("tests/fixtures/tfvars.partial.dev.json")).config
  image_tags = { "main/main" = "acrplatformdev.azurecr.io/partial:abc123" }
}

run "custom_module_receives_context" {
  command = plan

  assert {
    condition     = module.custom.context.resource_group_name == "rg-partial-dev"
    error_message = "custom module must receive the tool's resource group"
  }
  assert {
    condition     = module.custom.context.environment == "dev"
    error_message = "custom module must receive the environment"
  }
  assert {
    condition     = module.custom.context.tool_name == "partial"
    error_message = "custom module must receive the tool base name"
  }
  assert {
    condition     = module.custom.context.subnets.functions == var.config.platform.network.subnets.functions
    error_message = "custom module must receive the exact functions subnet id from platform config"
  }
  assert {
    condition     = module.custom.context.subnets.private_endpoints == var.config.platform.network.subnets.private_endpoints
    error_message = "custom module must receive the exact private_endpoints subnet id from platform config"
  }
  assert {
    condition     = module.custom.context.subnets.functions != module.custom.context.subnets.private_endpoints
    error_message = "functions and private_endpoints subnet ids must not be wired to the same value (would mask a swap)"
  }
  assert {
    condition     = module.custom.context.location == var.config.platform.location
    error_message = "custom module must receive the exact platform location"
  }
  assert {
    condition     = module.custom.context.vnet_id == var.config.platform.network.vnet_id
    error_message = "custom module must receive the exact platform vnet id"
  }
  assert {
    condition     = contains(keys(module.custom.context.app_identity_principal_ids), "main")
    error_message = "custom module must receive per-app identity principal ids"
  }
  assert {
    condition     = contains(keys(module.custom.context.function_identity_principal_ids), "relay")
    error_message = "custom module must receive per-function identity principal ids"
  }
}

# module.keyvault.id and .vault_uri are computed attributes of an azurerm_key_vault
# resource, so under mock_provider "azurerm" they are unknown at `plan` time and
# cannot be referenced in a plan-time assert condition at all (Terraform errors
# with "Unknown condition value" rather than evaluating to false). To get exact,
# swap-detecting values we override the mocked resource's id/vault_uri with
# distinguishable sentinels and make them available during plan.
run "custom_module_receives_keyvault_context" {
  command = plan

  override_resource {
    target = module.keyvault.azurerm_key_vault.this
    values = {
      id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-partial-dev/providers/Microsoft.KeyVault/vaults/kv-sentinel"
      vault_uri = "https://kv-sentinel.vault.azure.net/"
    }
    override_during = plan
  }

  assert {
    condition     = module.custom.context.key_vault_id == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-partial-dev/providers/Microsoft.KeyVault/vaults/kv-sentinel"
    error_message = "custom module must receive the key vault's exact id"
  }
  assert {
    condition     = module.custom.context.key_vault_uri == "https://kv-sentinel.vault.azure.net/"
    error_message = "custom module must receive the key vault's exact uri"
  }
  assert {
    condition     = module.custom.context.key_vault_id != module.custom.context.key_vault_uri
    error_message = "key_vault_id and key_vault_uri must not be wired to the same value (would mask a swap)"
  }
}
