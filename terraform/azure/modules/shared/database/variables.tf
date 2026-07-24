variable "name" {
  description = "Full server name (psql-... or sql-...)"
  type        = string
}

variable "type" {
  type = string

  validation {
    condition     = contains(["postgres", "sqlserver"], var.type)
    error_message = "type must be postgres or sqlserver"
  }
}

variable "size" {
  type = string
}

variable "storage_gb" {
  type = number
}

variable "public_access" {
  type = bool
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "keyvault_id" {
  type = string
}

variable "private_endpoints_subnet_id" {
  type = string
}

variable "private_dns_zone_id" {
  type = string
}

variable "dbs" {
  description = "Logical database name -> Key Vault secret name"
  type        = map(string)
}
