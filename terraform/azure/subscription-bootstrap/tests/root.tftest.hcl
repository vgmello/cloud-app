mock_provider "azurerm" {}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  location        = "eastus2"
  environment     = "dev"
  trusted_repo    = "vgmello/cloud-app"
}

run "custom_role_is_exactly_the_seven_capabilities" {
  command = plan

  assert {
    condition = length(setsubtract(
      azurerm_role_definition.bootstrap.permissions[0].actions,
      [
        "Microsoft.Resources/subscriptions/resourceGroups/read",
        "Microsoft.Resources/subscriptions/resourceGroups/write",
        "Microsoft.ManagedIdentity/userAssignedIdentities/read",
        "Microsoft.ManagedIdentity/userAssignedIdentities/write",
        "Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials/read",
        "Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials/write",
        "Microsoft.Authorization/roleAssignments/read",
        "Microsoft.Authorization/roleAssignments/write",
      ]
    )) == 0
    error_message = "bootstrap role must contain only the approved actions"
  }

  assert {
    condition     = !contains(azurerm_role_definition.bootstrap.permissions[0].actions, "*")
    error_message = "bootstrap role must not contain a wildcard action"
  }

  assert {
    condition     = length(azurerm_role_definition.bootstrap.permissions[0].actions) == 8
    error_message = "bootstrap role must contain exactly the eight approved actions"
  }

  assert {
    condition     = azurerm_federated_identity_credential.bootstrap.subject == "repo:vgmello/cloud-app:environment:dev"
    error_message = "bootstrap federation subject must trust the trusted repo environment"
  }

  assert {
    condition     = length(azurerm_role_assignment.bootstrap_state) == 0
    error_message = "no bootstrap state grant when state_account_id is empty"
  }
}

run "bootstrap_identity_gets_state_write" {
  command = plan

  variables {
    state_account_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-tfstate/providers/Microsoft.Storage/storageAccounts/sttfstatedev"
    state_container  = "tfstate"
  }

  assert {
    condition     = azurerm_role_assignment.bootstrap_state[0].role_definition_name == "Storage Blob Data Contributor"
    error_message = "bootstrap identity must read+write the state container"
  }
  assert {
    condition     = strcontains(azurerm_role_assignment.bootstrap_state[0].scope, "/blobServices/default/containers/tfstate")
    error_message = "bootstrap state grant must be scoped to the tfstate container"
  }
}

run "bootstrap_role_gains_no_storage_actions" {
  command = plan

  variables {
    subscription_id  = "00000000-0000-0000-0000-000000000000"
    location         = "eastus2"
    environment      = "dev"
    trusted_repo     = "vgmello/cloud-app"
    state_account_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-tfstate/providers/Microsoft.Storage/storageAccounts/sttfstatedev"
  }

  assert {
    condition = length([
      for a in azurerm_role_definition.bootstrap.permissions[0].actions :
      a if startswith(a, "Microsoft.Storage/")
    ]) == 0
    error_message = "the subscription-scoped bootstrap role must not gain storage actions"
  }

  assert {
    condition     = azurerm_role_assignment.state_container[0].scope == var.state_account_id
    error_message = "container-create rights must be scoped to the state account only"
  }
}
