locals {
  cfg      = var.config
  platform = local.cfg.platform
  env      = local.cfg.environment
  prefix   = try(local.platform.naming_prefix, "")

  # A stack may be split across several manifests ("components"), each with its
  # own Terraform state but all sharing one resource group and one Key Vault.
  # stack_base names what the stack shares; base names what this component owns,
  # so two components can never derive the same resource name. Mirrors
  # engine/cloudapp/naming.py.
  component  = try(local.cfg.component, "")
  stack_base = "${local.prefix}${local.cfg.name}"
  base       = local.component == "" ? local.stack_base : "${local.stack_base}-${local.component}"

  # The Key Vault is stack-wide, so exactly one component creates it: the
  # unnamed (root) one. Every other component reads it, which is also how a
  # component's apps get at secrets — including database URLs written by
  # whichever component owns the database.
  owns_keyvault = local.component == ""

  apps         = try(local.cfg.apps, {})
  functions    = try(local.cfg.functions, {})
  static_sites = try(local.cfg.static_sites, {})
  databases    = try(local.cfg.databases, {})
  db_legacy    = try(local.cfg.database_legacy, false)
  storage      = try(local.cfg.storage, null)

  # Entries another component owns. They stay in `databases`/`storage` because
  # the secret-name wiring below is derived from the declaration, not from the
  # resource — but nothing here creates them, so this component's state never
  # claims them and its applies never plan to destroy them.
  managed_databases = { for k, v in local.databases : k => v if !try(v.external, false) }
  manages_storage   = local.storage != null && !try(local.storage.external, false)

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

  # Stack-scoped: the bootstrap creates the resource group from the stack name,
  # and every component shares it and the Key Vault inside it.
  rg_name = "rg-${local.stack_base}-${local.env}"
  kv_name = trimsuffix(substr("kv-${local.stack_base}-${local.env}", 0, 24), "-")

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

  # Whichever of the two the component holds; the other is an empty list.
  keyvault_id        = local.owns_keyvault ? one(module.keyvault[*].id) : one(data.azurerm_key_vault.shared[*].id)
  keyvault_vault_uri = local.owns_keyvault ? one(module.keyvault[*].vault_uri) : one(data.azurerm_key_vault.shared[*].vault_uri)

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
