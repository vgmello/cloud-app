# Non-container (code) functions — design

## Goal

Let a manifest deploy an Azure Function from **application code** instead of a
container image. Today `functions:` is container-only: the engine auto-Dockerizes
any function lacking an `image`, and the Terraform module has a hard precondition
that a function must resolve to a container image. This design adds a **code
deploy** path — the Function App runs a native runtime stack (.NET, Node, Python,
Java, PowerShell) and receives its code as a zip via `az functionapp deployment
source config-zip`, after `terraform apply`.

Container functions are **unchanged**. The two paths coexist, switched by the
presence of a `runtime` field.

## Mode resolution

The optional `runtime` field is the mode switch. The artifact keys are `image`,
`docker` (a `{ file, context }` block — the builder Dockerfile), and `package`:

| `runtime` | artifact key     | build                                  | deploy target                                    |
| --------- | ---------------- | -------------------------------------- | ------------------------------------------------ |
| absent    | `image`          | none                                   | container **is** the function (existing)         |
| absent    | `docker`         | build image → push ACR                 | container **is** the function (existing)         |
| absent    | _none given_     | build `./Dockerfile` → push ACR        | container **is** the function (existing default) |
| present   | `package: ./dir` | none                                   | zip the dir → `config-zip`                       |
| present   | `docker`         | build image → run, `/out` volume → zip | zip → `config-zip`                               |
| present   | `image`          | run builder image, `/out` volume → zip | zip → `config-zip`                               |

Key semantic: when `runtime` is present, `image`/`docker` name a **throwaway
builder**, not the deploy artifact. The builder's job is to emit build output;
the platform zips that output and ships it as code. When `runtime` is absent,
behavior is exactly today's container deploy — including the existing default
where a function with neither `image` nor `docker` builds `./Dockerfile`.

**Artifact-key rules differ by mode:**

- **Container mode** (`runtime` absent): `image` XOR `docker`, or **neither**
  (defaults to `./Dockerfile`). Unchanged from today. `package` is rejected.
- **Code mode** (`runtime` present): **exactly one** of `image` | `docker` |
  `package` is required — there is no implicit-Dockerfile default, because the
  platform can't guess whether a runtime needs a build.

### Why a builder instead of platform-owned build toolchains

The platform never owns per-stack build logic (no `dotnet publish` / `npm ci` /
`pip install` baked into the action). Runtimes that need compilation supply a
Dockerfile or prebuilt image that does the build; runtimes that don't (Python,
PowerShell, plain Node) skip the builder and zip the source directly. This keeps
the platform runtime-agnostic and reuses the Docker capability the runner already
has.

## Manifest schema

### `runtime` (new)

Single string, `stack:version`, validated by a schema enum. Linux Function App
stacks only (`os_type = "Linux"`):

```yaml
functions:
  worker:
    runtime: dotnet-isolated:8.0
    package: ./scripts
```

Allowed values (enum — extend the enum to add a version):

| Value                 | Terraform `application_stack` mapping                          |
| --------------------- | -------------------------------------------------------------- |
| `dotnet-isolated:8.0` | `dotnet_version = "8.0"`, `use_dotnet_isolated_runtime = true` |
| `dotnet-isolated:9.0` | `dotnet_version = "9.0"`, `use_dotnet_isolated_runtime = true` |
| `node:20`             | `node_version = "20"`                                          |
| `node:22`             | `node_version = "22"`                                          |
| `python:3.11`         | `python_version = "3.11"`                                      |
| `python:3.12`         | `python_version = "3.12"`                                      |
| `java:17`             | `java_version = "17"`                                          |
| `java:21`             | `java_version = "21"`                                          |
| `powershell:7.4`      | `powershell_core_version = "7.4"`                              |

### `package` (new)

Optional string, path to the directory to zip when no build is needed. Requires
`runtime`. Mutually exclusive with `image`/`docker`.

### Schema constraints

- Add `runtime` (enum above) and `package` (string) to the function def.
- The existing rule forbids `image` + `docker`; keep it, and add: `package` is
  mutually exclusive with both `image` and `docker`, and `package` requires
  `runtime`.
- Container mode (no `runtime`) is unchanged: `image` XOR `docker` XOR neither
  (neither → default `./Dockerfile`); `package` rejected.
- Code mode (`runtime` present) requires exactly one of `image` | `docker` |
  `package` — no implicit-Dockerfile default.

> Note: the builder reuses the existing `docker: { file, context }` block — its
> `file` is the build Dockerfile. No new top-level `dockerfile` key is added; the
> spec's "Dockerfile builder" means `docker.file`.

## Engine changes

### `builds.py`

`enumerate_builds` currently enqueues an ACR image build for every function
without an `image`. Change:

- **Container functions** (no `runtime`): unchanged — enqueue ACR build/push.
- **Code functions** (`runtime` present): **do not** enqueue an ACR push. Instead:
  - `package` set → no build; record a "zip directory" package task.
  - `docker`/`image` builder → record a "build-and-run" package task: build the
    image locally (if Dockerfile), `docker run -v <tmpdir>:/out <image>`, then zip
    `<tmpdir>`.

The builder container is **never pushed** to ACR. It runs on the same runner that
builds container images today; output volume, zip, and deploy all happen there.

### New deploy step (post-apply)

After `terraform apply`, for each code function:

```
az functionapp deployment source config-zip \
  -g <resource-group> -n <function-app-name> --src <function>.zip
```

Runs under the OIDC deploy service principal already used for apply. The Function
App must exist first — this is why deploy is post-apply (ordering flips vs
container, where the image must exist before apply).

## Terraform module (`modules/function`)

- **Precondition**: relax from `image != null` to `image != null || runtime != null`.
  Error message updated: a code function is valid with no image.
- **`application_stack`**: branch on mode.
  - `image != null` → existing `docker { registry_url / image_name / image_tag }`.
  - `runtime != null` → map the enum value to the correct native stack arg (table
    above). Exactly one native stack argument set.
- **SKU**: unchanged — `EP1` (Elastic Premium). Keeps VNet integration and the
  private-by-default posture. Consumption/Flex is explicitly out of scope.
- **ACR role assignment**: only required for container functions. For a code
  function with no image, the `AcrPull` role assignment is unnecessary but harmless
  to keep; leave as-is to minimize module churn unless it errors.
- Terraform creates the app **empty** (native stack, no code). Code lands via the
  post-apply deploy step.

## Runner / connectivity

Private-by-default means the Function App's **SCM/Kudu endpoint** is reachable only
inside the VNet. A GitHub-hosted runner cannot reach it for `config-zip`.

Resolution: the **entire deploy job runs on a self-hosted runner inside the VNet**.
`runs-on` is a caller job-level field — a composite action inherits its caller's
runner and cannot self-select — so this is set by the app team's workflow, not by
a new action input. `terraform apply`, the builder `docker run`, the zip, and
`config-zip` all execute on that runner.

The self-hosted VNet runner must have: `terraform`, `az` CLI, and `docker`.

Sample/generated workflow documents the split:

```yaml
jobs:
  deploy:
    runs-on: [self-hosted, vnet-dev] # PR/plan may still use ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: vgmello/cloud-app/.github/actions/cloud-app@v1
        with: { env: dev }
```

No `runs_on`/`deploy_runner` input is added to the action — it would be inert,
since a composite cannot change its runner.

## Testing

- **pytest**
  - mode resolution: exactly-one-of `image`/`docker`/`package` in code mode; `package`
    requires `runtime`; `runtime` + each artifact key resolves to the right task.
  - `builds.py`: code functions do **not** enqueue an ACR push; container functions
    still do.
  - deploy-step command construction (rg/name/src) for a code function.
- **golden fixtures**: add `runtime` + `package` and `runtime` + builder cases to
  the builds goldens.
- **terraform `tftest`**: a `runtime` function renders the correct
  `application_stack` native args and **no** `docker` block; precondition passes
  with `runtime` and no image.

## Out of scope

- Consumption / Flex Consumption SKUs.
- Platform-owned build toolchains (per-stack `publish`/`build`).
- `WEBSITE_RUN_FROM_PACKAGE` blob deploy (config-zip is the chosen mechanic).
- Windows Function App stacks.
- Provisioning the self-hosted VNet runner (a landing-zone prerequisite, like the
  deploy SPs).
