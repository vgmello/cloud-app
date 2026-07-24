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
