locals {
  cfg      = var.config
  platform = local.cfg.platform
  env      = local.cfg.environment
  prefix   = try(local.platform.naming_prefix, "")
  base     = "${local.prefix}${local.cfg.name}"

  apps         = try(local.cfg.apps, {})
  functions    = try(local.cfg.functions, {})
  static_sites = try(local.cfg.static_sites, {})
  databases    = try(local.cfg.databases, {})
  db_legacy    = try(local.cfg.database_legacy, false)
  storage      = try(local.cfg.storage, null)

  # entry base name: explicit name > manifest name (single entry) > manifest name + key
  app_bases = {
    for k, v in local.apps :
    k => coalesce(try(v.name, null), length(local.apps) == 1 ? local.base : "${local.base}-${k}")
  }
  function_bases = {
    for k, v in local.functions :
    k => coalesce(try(v.name, null), length(local.functions) == 1 ? local.base : "${local.base}-${k}")
  }
  static_site_bases = {
    for k, v in local.static_sites :
    k => coalesce(try(v.name, null), length(local.static_sites) == 1 ? local.base : "${local.base}-${k}")
  }

  ca_names   = { for k, b in local.app_bases : k => "ca-${b}-${local.env}" }
  func_names = { for k, b in local.function_bases : k => "func-${b}-${local.env}" }
  swa_names  = { for k, b in local.static_site_bases : k => "swa-${b}-${local.env}" }

  rg_name = "rg-${local.base}-${local.env}"
  kv_name = trimsuffix(substr("kv-${local.base}-${local.env}", 0, 24), "-")
  st_name = substr("st${replace("${local.base}${local.env}", "-", "")}", 0, 24)

  db_server_bases = {
    for k, v in local.databases :
    k => coalesce(try(v.name, null), length(local.databases) == 1 ? local.base : "${local.base}-${k}")
  }
  db_names = {
    for k, v in local.databases :
    k => v.type == "postgres" ? "psql-${local.db_server_bases[k]}-${local.env}" : "sql-${local.db_server_bases[k]}-${local.env}"
  }
  db_secret_names = {
    for sk, sv in local.databases :
    sk => {
      for db in sv.dbs :
      db => local.db_legacy ? "database-url" : "database-url-${sk}-${db}"
    }
  }

  acr_name = split(".", local.platform.acr.login_server)[0]
  acr_id   = "/subscriptions/${local.platform.subscription_id}/resourceGroups/${local.platform.acr.resource_group}/providers/Microsoft.ContainerRegistry/registries/${local.acr_name}"

  # reserved env var -> Key Vault secret name wiring for platform-generated secrets
  storage_secret_env = local.storage != null ? { STORAGE_CONNECTION = "storage-connection" } : {}

  db_blanket_env = local.db_legacy ? { DATABASE_URL = "database-url" } : {}

  per_app_db_env = {
    for ak, av in local.apps :
    ak => local.db_legacy ? local.db_blanket_env : {
      for ref in try(av.databases, []) :
      "${upper(replace(split("/", ref)[0], "-", "_"))}_${upper(replace(split("/", ref)[1], "-", "_"))}_DATABASE_URL"
      => local.db_secret_names[split("/", ref)[0]][split("/", ref)[1]]
    }
  }

  per_function_db_env = {
    for fk, fv in local.functions :
    fk => local.db_legacy ? local.db_blanket_env : {
      for ref in try(fv.databases, []) :
      "${upper(replace(split("/", ref)[0], "-", "_"))}_${upper(replace(split("/", ref)[1], "-", "_"))}_DATABASE_URL"
      => local.db_secret_names[split("/", ref)[0]][split("/", ref)[1]]
    }
  }
}
