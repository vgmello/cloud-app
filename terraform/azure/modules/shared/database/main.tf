locals {
  pg_sku  = { small = "B_Standard_B1ms", medium = "GP_Standard_D2ds_v4", large = "GP_Standard_D4ds_v4" }
  sql_sku = { small = "S0", medium = "S2", large = "S4" }

  is_postgres = var.type == "postgres"
  fqdn        = local.is_postgres ? "${var.name}.postgres.database.azure.com" : "${var.name}.database.windows.net"

  connection_strings = {
    for db, _ in var.dbs :
    db => local.is_postgres ? (
      "postgresql://dbadmin:${random_password.admin.result}@${local.fqdn}:5432/${db}?sslmode=require"
      ) : (
      "Server=tcp:${local.fqdn},1433;Database=${db};User ID=dbadmin;Password=${random_password.admin.result};Encrypt=true;"
    )
  }
}

resource "random_password" "admin" {
  length  = 32
  special = false
}

resource "azurerm_postgresql_flexible_server" "this" {
  count = local.is_postgres ? 1 : 0

  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  version                       = "16"
  administrator_login           = "dbadmin"
  administrator_password        = random_password.admin.result
  sku_name                      = local.pg_sku[var.size]
  storage_mb                    = var.storage_gb * 1024
  public_network_access_enabled = var.public_access
  zone                          = "1"
}

resource "azurerm_postgresql_flexible_server_database" "this" {
  for_each = local.is_postgres ? var.dbs : {}

  name      = each.key
  server_id = azurerm_postgresql_flexible_server.this[0].id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_mssql_server" "this" {
  count = local.is_postgres ? 0 : 1

  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  version                       = "12.0"
  administrator_login           = "dbadmin"
  administrator_login_password  = random_password.admin.result
  minimum_tls_version           = "1.2"
  public_network_access_enabled = var.public_access
}

resource "azurerm_mssql_database" "this" {
  for_each = local.is_postgres ? {} : var.dbs

  name        = each.key
  server_id   = azurerm_mssql_server.this[0].id
  sku_name    = local.sql_sku[var.size]
  max_size_gb = var.storage_gb
}

module "private_endpoint" {
  source = "../private-endpoint"
  count  = var.public_access ? 0 : 1

  name                = "pe-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoints_subnet_id
  target_resource_id  = local.is_postgres ? azurerm_postgresql_flexible_server.this[0].id : azurerm_mssql_server.this[0].id
  subresource         = local.is_postgres ? "postgresqlServer" : "sqlServer"
  private_dns_zone_id = var.private_dns_zone_id
}

resource "azurerm_key_vault_secret" "database_url" {
  for_each = var.dbs

  name         = each.value
  value        = local.connection_strings[each.key]
  key_vault_id = var.keyvault_id
}

# Legacy single-database deployments (singular `database:` manifest, normalized to
# logical db "main") were provisioned when these resources were count-gated ([0]) or
# a single unindexed resource. These blocks move existing state in place instead of
# destroying/recreating on upgrade to the for_each-keyed resources. No-ops for fresh
# deploys or when the legacy server used the other engine (e.g. mssql db absent when
# the legacy server was postgres).
moved {
  from = azurerm_postgresql_flexible_server_database.this[0]
  to   = azurerm_postgresql_flexible_server_database.this["main"]
}

moved {
  from = azurerm_mssql_database.this[0]
  to   = azurerm_mssql_database.this["main"]
}

moved {
  from = azurerm_key_vault_secret.database_url
  to   = azurerm_key_vault_secret.database_url["main"]
}
