output "function_name" {
  value = azurerm_linux_function_app.this.name
}

output "default_hostname" {
  value = azurerm_linux_function_app.this.default_hostname
}

output "plan_sku" {
  value = azurerm_service_plan.this.sku_name
}

output "docker_image" {
  description = "Parsed docker stack settings, null when the function has no image"
  value = local.image == null ? null : {
    registry_url = "https://${local.image_registry}"
    image_name   = local.image_repo
    image_tag    = local.image_tag_part
  }
}

output "runtime_stack" {
  description = "The manifest runtime value (stack:version), null for container functions"
  value       = local.runtime
}

output "native_stack" {
  description = "The resolved native application_stack arguments actually rendered on the function app (same locals the resource block consumes), null for container functions"
  value = local.runtime == null ? null : {
    dotnet_version              = local.native_dotnet_version
    use_dotnet_isolated_runtime = local.native_use_dotnet_isolated_runtime
    node_version                = local.native_node_version
    python_version              = local.native_python_version
    java_version                = local.native_java_version
    powershell_core_version     = local.native_powershell_core_version
  }
}
