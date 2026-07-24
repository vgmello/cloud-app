output "names" {
  description = "Every resource name the naming convention produces for this tool+env"
  value = {
    resource_group = local.rg_name
    keyvault       = local.kv_name
    storage        = local.storage != null ? local.st_name : null
    databases      = local.db_names
    apps           = local.ca_names
    functions      = local.func_names
    static_sites   = local.swa_names
  }
}

output "app_fqdns" {
  value = { for k, m in module.container_app : k => m.fqdn }
}

output "function_hostnames" {
  value = { for k, m in module.function : k => m.default_hostname }
}

output "static_site_hostnames" {
  value = { for k, m in module.static_site : k => m.default_host_name }
}
