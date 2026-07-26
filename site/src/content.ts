export const REPO_URL = "https://github.com/vgmello/cloud-app";

export const DOCS = {
  repo: REPO_URL,
  usage: `${REPO_URL}/blob/main/docs/usage.md`,
  trust: `${REPO_URL}/blob/main/docs/trust-modes.md`,
  license: `${REPO_URL}/blob/main/LICENSE`,
} as const;

export interface CodeSample {
  readonly id: string;
  readonly filename: string;
  readonly label: string;
  readonly kind: "manifest" | "workflow" | "resources";
  readonly code: string;
}

export const SAMPLES: readonly CodeSample[] = [
  {
    id: "hero-manifest",
    filename: "cloud-app.yml",
    label: "The manifest",
    kind: "manifest",
    code: `name: orders-api
app:
  port: 8080
  ingress: internal
database:
  size: small
environments:
  dev: {}
  prod:
    database:
      size: medium
`,
  },
  {
    id: "hero-workflow",
    filename: ".github/workflows/deploy.yml",
    label: "The workflow",
    kind: "workflow",
    code: `name: deploy
on:
  push: { branches: [main] }
  pull_request:
permissions: { contents: read, id-token: write }
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - uses: actions/checkout@v4
      - uses: vgmello/cloud-app/.github/actions/cloud-app@v1
        with:
          env: dev
          plan_only: \${{ github.event_name == 'pull_request' }}
          app-id: \${{ secrets.APP_ID }}
          app-private-key: \${{ secrets.APP_PRIVATE_KEY }}
`,
  },
  {
    id: "hero-resources",
    filename: "Resources created",
    label: "Resources created",
    kind: "resources",
    code: `# terraform plan → 11 resources, none of which you wrote

module.keyvault.azurerm_key_vault.this                                             kv-orders-api-dev
module.keyvault.module.private_endpoint.azurerm_private_endpoint.this
module.container_app["main"].azurerm_user_assigned_identity.this
module.container_app["main"].azurerm_role_assignment.keyvault
module.container_app["main"].azurerm_role_assignment.acr
module.container_app["main"].azurerm_container_app.this                            ca-orders-api-dev
module.database["main"].random_password.admin
module.database["main"].azurerm_postgresql_flexible_server.this[0]                 psql-orders-api-dev
module.database["main"].azurerm_postgresql_flexible_server_database.this["main"]
module.database["main"].module.private_endpoint[0].azurerm_private_endpoint.this
module.database["main"].azurerm_key_vault_secret.database_url["main"]              database-url
`,
  },
  {
    id: "stack-manifest",
    filename: "cloud-app.yml",
    label: "Manifest",
    kind: "manifest",
    code: `name: orders-api
app:
  port: 8080
  ingress: internal
database:
  size: small
`,
  },
  {
    id: "environments-manifest",
    filename: "cloud-app.yml",
    label: "Environments",
    kind: "manifest",
    code: `name: orders-api
app:
  port: 8080
database:
  size: small
environments:
  dev: {}
  prod:
    database:
      size: medium
`,
  },
  {
    id: "custom-terraform-manifest",
    filename: "cloud-app.yml",
    label: "Custom Terraform",
    kind: "manifest",
    code: `name: orders-api
app:
  port: 8080
terraform: ./terraform
`,
  },
  {
    id: "capabilities-manifest",
    filename: "cloud-app.yml",
    label: "Everything at once",
    kind: "manifest",
    code: `name: orders-api
apps:
  api:
    port: 8080
functions:
  worker:
    runtime: dotnet-isolated:8.0
    package: ./publish
static_sites:
  web: {}
database:
  type: postgres
  size: small
storage:
  containers: [uploads]
`,
  },
];

export function sample(id: string): CodeSample {
  const found = SAMPLES.find((entry) => entry.id === id);
  if (!found) throw new Error(`unknown code sample: ${id}`);
  return found;
}
