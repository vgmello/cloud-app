mock_provider "azurerm" {}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  location        = "eastus2"
  name            = "orders-api"
  environment     = "prod"
  plan_subjects   = ["repo:acme/orders:pull_request"]
  apply_subjects  = ["repo:acme/orders:environment:prod"]
}

run "identities_and_scoped_roles" {
  command = plan

  assert {
    condition     = azurerm_resource_group.this.name == "rg-orders-api-prod"
    error_message = "resource group name"
  }
  assert {
    condition     = azurerm_role_assignment.plan_reader.role_definition_name == "Reader"
    error_message = "plan identity must be Reader"
  }
  assert {
    condition     = azurerm_role_assignment.apply_contributor.role_definition_name == "Contributor"
    error_message = "apply identity must be Contributor"
  }
  assert {
    condition     = azurerm_role_assignment.plan_blob.role_definition_name == "Storage Blob Data Reader" && azurerm_role_assignment.plan_kv.role_definition_name == "Key Vault Reader"
    error_message = "plan identity must get the data-plane reader roles for refresh"
  }
  assert {
    condition     = azurerm_federated_identity_credential.apply[0].subject == "repo:acme/orders:environment:prod"
    error_message = "apply federation subject passthrough"
  }
  assert {
    condition     = length(azurerm_role_assignment.apply_acr_push) == 0
    error_message = "no ACR push grant when acr_id is empty"
  }
  assert {
    condition     = length(azurerm_role_assignment.plan_state) == 0 && length(azurerm_role_assignment.apply_state) == 0
    error_message = "no state-container grants when state_account_id is empty"
  }
}

run "state_container_grants" {
  command = plan

  # resource_manager_id is computed; pin it so the grant scope is
  # comparable during plan.
  override_resource {
    target          = azurerm_storage_container.state[0]
    override_during = plan
    values = {
      resource_manager_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-tfstate/providers/Microsoft.Storage/storageAccounts/sttfstateprod/blobServices/default/containers/tfstate"
    }
  }

  variables {
    state_account_id      = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-tfstate/providers/Microsoft.Storage/storageAccounts/sttfstateprod"
    stack_state_container = "tfstate"
  }

  assert {
    condition     = azurerm_role_assignment.plan_state[0].role_definition_name == "Storage Blob Data Reader"
    error_message = "plan identity must read the state container"
  }
  assert {
    condition     = azurerm_role_assignment.apply_state[0].role_definition_name == "Storage Blob Data Contributor"
    error_message = "apply identity must read+write the state container"
  }
  assert {
    condition     = azurerm_role_assignment.apply_state[0].scope == azurerm_storage_container.state[0].resource_manager_id
    error_message = "state grant must be scoped to the stack's own container"
  }
}

run "state_container_is_per_stack_and_grants_scope_to_it" {
  command = plan

  # resource_manager_id is computed; pin it so the grant scope is
  # comparable during plan.
  override_resource {
    target          = azurerm_storage_container.state[0]
    override_during = plan
    values = {
      resource_manager_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-tfstate/providers/Microsoft.Storage/storageAccounts/sttfstatedev/blobServices/default/containers/orders-dev"
    }
  }

  variables {
    name                  = "orders"
    environment           = "dev"
    subscription_id       = "00000000-0000-0000-0000-000000000000"
    location              = "eastus2"
    plan_subjects         = ["repo:acme/orders:pull_request"]
    apply_subjects        = ["repo:acme/orders:environment:dev"]
    state_account_id      = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-tfstate/providers/Microsoft.Storage/storageAccounts/sttfstatedev"
    stack_state_container = "orders-dev"
  }

  assert {
    condition     = azurerm_storage_container.state[0].name == "orders-dev"
    error_message = "the stack must get its own per-(stack, env) state container"
  }

  assert {
    condition     = azurerm_role_assignment.apply_state[0].scope == azurerm_storage_container.state[0].resource_manager_id
    error_message = "apply state grant must scope to this stack's container, not a shared one"
  }

  assert {
    condition     = azurerm_role_assignment.plan_state[0].scope == azurerm_storage_container.state[0].resource_manager_id
    error_message = "plan state grant must scope to this stack's container, not a shared one"
  }
}

run "acr_push_scoped_to_repo_namespace" {
  command = plan

  variables {
    acr_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-platform-prod/providers/Microsoft.ContainerRegistry/registries/acrplatformprod"
  }

  assert {
    condition     = azurerm_role_assignment.apply_acr_push[0].role_definition_name == "Container Registry Repository Writer"
    error_message = "apply identity must get repo Writer on the ACR"
  }
  assert {
    condition     = strcontains(azurerm_role_assignment.apply_acr_push[0].condition, "StringStartsWithIgnoreCase 'orders-api/'")
    error_message = "ACR push must be ABAC-scoped to the tool repository namespace"
  }
}
