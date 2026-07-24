variable "subscription_id" {
  type = string
}

variable "location" {
  type = string
}

variable "environment" {
  type = string
}

variable "trusted_repo" {
  description = "owner/name of the repo whose environment subject the bootstrap identity trusts"
  type        = string
}

variable "state_account_id" {
  description = "Resource ID of the Azure Blob tfstate storage account. Empty disables the bootstrap identity's state grant."
  type        = string
  default     = ""
}

variable "state_container" {
  description = "tfstate blob container name. Grants scope to this container when set; to the whole account otherwise."
  type        = string
  default     = ""
}
