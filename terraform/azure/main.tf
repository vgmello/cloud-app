# The resource group is owned by the bootstrap stack (it also holds the
# plan/apply identities). The main stack only consumes it — two Terraform states
# must never both manage the same RG.
data "azurerm_resource_group" "this" {
  name = local.rg_name
}

module "keyvault" {
  source = "./modules/shared/keyvault"
  count  = local.owns_keyvault ? 1 : 0

  name                        = local.kv_name
  location                    = local.platform.location
  resource_group_name         = data.azurerm_resource_group.this.name
  tenant_id                   = local.platform.tenant_id
  public_network_access       = local.platform.runner_access == "public-allowlist"
  runner_ip                   = var.runner_ip
  private_endpoints_subnet_id = local.platform.network.subnets.private_endpoints
  private_dns_zone_id         = local.platform.network.private_dns_zone_ids.keyvault
}

# The Key Vault used to be unconditional. Gating it on count renames the module
# instance, so move existing state instead of destroying and recreating a vault
# full of live secrets. No-op for fresh deploys.
moved {
  from = module.keyvault
  to   = module.keyvault[0]
}

# A named component does not create the stack's Key Vault — it reads the one the
# root component created. This fails if the root component has never been
# deployed, which is the correct order: the stack's shared services first.
data "azurerm_key_vault" "shared" {
  count = local.owns_keyvault ? 0 : 1

  name                = local.kv_name
  resource_group_name = data.azurerm_resource_group.this.name
}

# Only the databases this component owns. Entries marked `external: true` belong
# to another component of the same stack: they still shape the Key Vault secret
# names apps are wired to (locals.db_secret_names), but nothing is created for
# them here and this component's state never claims them.
module "database" {
  source   = "./modules/shared/database"
  for_each = local.managed_databases

  name                        = local.db_names[each.key]
  type                        = each.value.type
  size                        = each.value.size
  storage_gb                  = each.value.storage_gb
  public_access               = each.value.public_access
  dbs                         = local.db_secret_names[each.key]
  location                    = local.platform.location
  resource_group_name         = data.azurerm_resource_group.this.name
  keyvault_id                 = local.keyvault_id
  private_endpoints_subnet_id = local.platform.network.subnets.private_endpoints
  private_dns_zone_id         = each.value.type == "postgres" ? local.platform.network.private_dns_zone_ids.postgres : local.platform.network.private_dns_zone_ids.sqlserver
}

# Legacy single-database deployments (singular `database:` manifest, normalized to
# server key "main") were provisioned when module.database was count-gated ([0]).
# This block moves existing state in place instead of destroying/recreating on
# upgrade to the for_each-keyed module. No-op for fresh deploys or non-legacy state.
moved {
  from = module.database[0]
  to   = module.database["main"]
}

module "storage" {
  source = "./modules/shared/storage"
  count  = local.manages_storage ? 1 : 0

  name                        = local.st_name
  location                    = local.platform.location
  resource_group_name         = data.azurerm_resource_group.this.name
  containers                  = try(local.storage.containers, [])
  public_access               = local.storage.public_access
  runner_ip                   = var.runner_ip
  keyvault_id                 = local.keyvault_id
  private_endpoints_subnet_id = local.platform.network.subnets.private_endpoints
  private_dns_zone_id         = local.platform.network.private_dns_zone_ids.blob
}

module "container_app" {
  source   = "./modules/container-app"
  for_each = local.apps

  name                          = local.ca_names[each.key]
  location                      = local.platform.location
  resource_group_name           = data.azurerm_resource_group.this.name
  container_apps_environment_id = local.platform.container_apps_environment_id
  app                           = each.value
  image_tags                    = { for k, v in var.image_tags : split("/", k)[1] => v if length(split("/", k)) == 2 && split("/", k)[0] == each.key }
  acr_login_server              = local.platform.acr.login_server
  acr_id                        = local.acr_id
  keyvault_id                   = local.keyvault_id
  keyvault_vault_uri            = local.keyvault_vault_uri
  extra_secret_env              = merge(local.storage_secret_env, local.per_app_db_env[each.key])

  depends_on = [module.database, module.storage]
}

module "function" {
  source   = "./modules/function"
  for_each = local.functions

  name                = local.func_names[each.key]
  location            = local.platform.location
  resource_group_name = data.azurerm_resource_group.this.name
  function            = each.value
  image_tag           = try(var.image_tags[each.key], null)
  acr_id              = local.acr_id
  keyvault_id         = local.keyvault_id
  keyvault_vault_uri  = local.keyvault_vault_uri
  extra_secret_env    = merge(local.storage_secret_env, local.per_function_db_env[each.key])
  functions_subnet_id = local.platform.network.subnets.functions

  depends_on = [module.database, module.storage]
}

module "static_site" {
  source   = "./modules/static-site"
  for_each = local.static_sites

  name                = local.swa_names[each.key]
  location            = local.platform.location
  resource_group_name = data.azurerm_resource_group.this.name
  site                = each.value
}

# Caller-supplied Terraform. Always declared; the module ships empty and creates
# nothing until the action copies the caller's *.tf into ./custom. It runs in the
# main stack, so it applies under the RG-scoped apply identity — that scope is
# what confines custom resources to this tool's resource group.
module "custom" {
  source = "./custom"

  resource_group_name             = data.azurerm_resource_group.this.name
  location                        = local.platform.location
  environment                     = local.env
  tool_name                       = local.base
  vnet_id                         = local.platform.network.vnet_id
  subnets                         = local.platform.network.subnets
  key_vault_id                    = local.keyvault_id
  key_vault_uri                   = local.keyvault_vault_uri
  app_identity_principal_ids      = { for k, m in module.container_app : k => m.identity_principal_id }
  function_identity_principal_ids = { for k, m in module.function : k => m.identity_principal_id }
}
