output "names" {
  description = <<-EOT
    Every resource name the naming convention produces for this component.
    resource_group and keyvault are stack-wide (shared by every component);
    storage and databases are null/absent when another component owns them.
  EOT
  value = {
    component      = local.component
    resource_group = local.rg_name
    keyvault       = local.kv_name
    storage        = local.manages_storage ? local.st_name : null
    databases      = { for k in keys(local.managed_databases) : k => local.db_names[k] }
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
