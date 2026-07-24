# The resource group is owned by the bootstrap stack (it also holds the
# plan/apply identities). The main stack only consumes it — two Terraform states
# must never both manage the same RG.
data "azurerm_resource_group" "this" {
  name = local.rg_name
}

module "keyvault" {
  source = "./modules/shared/keyvault"

  name                        = local.kv_name
  location                    = local.platform.location
  resource_group_name         = data.azurerm_resource_group.this.name
  tenant_id                   = local.platform.tenant_id
  public_network_access       = local.platform.runner_access == "public-allowlist"
  runner_ip                   = var.runner_ip
  private_endpoints_subnet_id = local.platform.network.subnets.private_endpoints
  private_dns_zone_id         = local.platform.network.private_dns_zone_ids.keyvault
}

module "database" {
  source   = "./modules/shared/database"
  for_each = local.databases

  name                        = local.db_names[each.key]
  type                        = each.value.type
  size                        = each.value.size
  storage_gb                  = each.value.storage_gb
  public_access               = each.value.public_access
  dbs                         = local.db_secret_names[each.key]
  location                    = local.platform.location
  resource_group_name         = data.azurerm_resource_group.this.name
  keyvault_id                 = module.keyvault.id
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
  count  = local.storage != null ? 1 : 0

  name                        = local.st_name
  location                    = local.platform.location
  resource_group_name         = data.azurerm_resource_group.this.name
  containers                  = try(local.storage.containers, [])
  public_access               = local.storage.public_access
  runner_ip                   = var.runner_ip
  keyvault_id                 = module.keyvault.id
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
  keyvault_id                   = module.keyvault.id
  keyvault_vault_uri            = module.keyvault.vault_uri
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
  keyvault_id         = module.keyvault.id
  keyvault_vault_uri  = module.keyvault.vault_uri
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
