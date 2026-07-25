# cloud-app Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a single static landing page for the cloud-app platform at `site/`, published to GitHub Pages.

**Architecture:** Section modules written in TypeScript render HTML strings. A prerender step composes them into `index.html` at build time, so the shipped page is fully static and readable without JavaScript. A small set of behaviour modules (tabs, copy, reveal, connectors) progressively enhance that static markup. Tailwind v4 supplies utilities over a hand-defined OKLCH token set.

**Tech Stack:** Vite 7, bun 1.3, TypeScript 5 (strict), Tailwind CSS v4 via `@tailwindcss/vite`, Vitest + jsdom, ajv + yaml (schema tests), culori (contrast tests), self-hosted Fontsource fonts.

**Spec:** `docs/superpowers/specs/2026-07-25-landing-page-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- All site code lives under `site/`. Never modify `engine/`, `terraform/`, or `environments/`.
- Package manager and runner is **bun** (`bun install`, `bun run …`). Never npm or yarn.
- Vite `base` is `/cloud-app/` (the GitHub Pages project path for `github.com/vgmello/cloud-app`).
- Theme tokens are OKLCH, defined once in `site/src/styles.css` under `@theme`. Exact values:
  - `--color-bg: oklch(0.145 0.005 260)`
  - `--color-surface: oklch(0.185 0.006 260)`
  - `--color-line: oklch(0.26 0.008 260)`
  - `--color-ink: oklch(0.96 0.003 260)`
  - `--color-muted: oklch(0.72 0.008 260)`
  - `--color-accent: oklch(0.78 0.13 180)`
- Contrast floors, enforced by test: muted-on-bg ≥ 4.5:1, ink-on-bg ≥ 4.5:1, accent-on-bg ≥ 3:1.
- Hero display size caps at `4.5rem`. Heading letter-spacing never tighter than `-0.04em`. Body measure 65–75ch.
- **Banned:** eyebrow kickers above section headings (the hero carries exactly one, nowhere else), numbered section markers outside "How it works", gradient text (`background-clip: text`), side-stripe borders, decorative glassmorphism, identical icon-card grids.
- All motion uses exponential ease-out (`--ease-out-quint: cubic-bezier(0.22, 1, 0.36, 1)`). No bounce, no elastic.
- Every animation has a `prefers-reduced-motion: reduce` alternative. Reveal states are applied **by JavaScript only** — content is visible in the static HTML.
- Every YAML manifest sample on the page must validate against `terraform/schema/cloud-app.schema.json`. This is enforced by test.
- All documentation links derive from the single `REPO_URL` constant in `site/src/content.ts`.
- Test command is `bun run test` from `site/`. Build command is `bun run build` from `site/`.

---

## File Structure

**Created in `site/`:**

| Path                       | Responsibility                                               |
| -------------------------- | ------------------------------------------------------------ |
| `package.json`             | scripts + dependencies                                       |
| `tsconfig.json`            | strict TypeScript config                                     |
| `vite.config.ts`           | Vite + Tailwind plugin + prerender plugin + Vitest config    |
| `.gitignore`               | ignores `node_modules`, `dist`, generated `index.html`       |
| `index.template.html`      | document shell with a `<!--SECTIONS-->` marker               |
| `src/prerender.ts`         | `renderDocument()` — composes sections into the template     |
| `src/main.ts`              | entry: imports styles/fonts, wires behaviours                |
| `src/styles.css`           | Tailwind import, `@theme` tokens, component + motion classes |
| `src/content.ts`           | every URL, code sample, and body string, typed               |
| `src/lib/html.ts`          | `html` tagged template + `escapeHtml`                        |
| `src/sections/index.ts`    | `Section` interface + ordered `SECTIONS` array               |
| `src/sections/*.ts`        | one module per section (8 total)                             |
| `src/behaviors/tabs.ts`    | ARIA tabs pattern                                            |
| `src/behaviors/copy.ts`    | copy-to-clipboard + live region                              |
| `src/behaviors/reveal.ts`  | scroll reveals, reduced-motion aware                         |
| `src/behaviors/connect.ts` | manifest→stack connector lines                               |
| `tests/*.test.ts`          | one test file per module above                               |

**Created at repo root:** `.github/workflows/site.yml`.

---

## Task 1: Scaffold the site and lock the token system

**Files:**

- Create: `site/package.json`, `site/tsconfig.json`, `site/vite.config.ts`, `site/.gitignore`, `site/index.template.html`, `site/src/styles.css`, `site/src/main.ts`, `site/src/sections/index.ts`, `site/src/prerender.ts`
- Test: `site/tests/tokens.test.ts`

**Interfaces:**

- Consumes: nothing.
- Produces: `Section` interface (`{ readonly id: string; render(): string }`) and `SECTIONS: readonly Section[]` from `src/sections/index.ts`; `renderDocument(template: string): string` from `src/prerender.ts`.

- [ ] **Step 1: Create the directory and install dependencies**

```bash
mkdir -p site/src/sections site/src/behaviors site/src/lib site/tests
cd site
bun init -y
bun add -d vite@^7 typescript@^5 tailwindcss@^4 @tailwindcss/vite@^4 vitest@^3 jsdom@^26 ajv@^8 yaml@^2 culori@^4 @types/culori@^4
bun add @fontsource-variable/inter @fontsource-variable/jetbrains-mono
```

- [ ] **Step 2: Write `site/package.json`**

`bun init` leaves an `index.ts` and a `README.md` at `site/`. Delete both — `site/README.md` is written properly in Task 11:

```bash
rm -f site/index.ts site/README.md
```

Then overwrite `site/package.json`, keeping the `dependencies` and `devDependencies` blocks bun wrote:

```json
{
  "name": "cloud-app-site",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

- [ ] **Step 3: Write `site/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "types": ["vite/client"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noEmit": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "verbatimModuleSyntax": true
  },
  "include": ["src", "tests", "vite.config.ts"]
}
```

- [ ] **Step 4: Write `site/.gitignore`**

`index.html` is generated by the prerender step and must never be committed.

```gitignore
node_modules/
dist/
index.html
```

- [ ] **Step 5: Write the failing token test — `site/tests/tokens.test.ts`**

```typescript
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { wcagContrast } from "culori";

const css = readFileSync(
  fileURLToPath(new URL("../src/styles.css", import.meta.url)),
  "utf8",
);

function token(name: string): string {
  const match = css.match(new RegExp(`--color-${name}:\\s*([^;]+);`));
  if (!match?.[1])
    throw new Error(`token --color-${name} not found in src/styles.css`);
  return match[1].trim();
}

describe("theme tokens", () => {
  it("body text clears WCAG AA against the page background", () => {
    expect(wcagContrast(token("muted"), token("bg"))).toBeGreaterThanOrEqual(
      4.5,
    );
  });

  it("headings clear WCAG AA against the page background", () => {
    expect(wcagContrast(token("ink"), token("bg"))).toBeGreaterThanOrEqual(4.5);
  });

  it("the accent clears AA for large text and UI against the page background", () => {
    expect(wcagContrast(token("accent"), token("bg"))).toBeGreaterThanOrEqual(
      3,
    );
  });

  it("surface is distinguishable from the page background", () => {
    expect(wcagContrast(token("surface"), token("bg"))).toBeGreaterThan(1);
  });
});
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `cd site && bun run test tests/tokens.test.ts`
Expected: FAIL — `ENOENT` / `no such file or directory` for `src/styles.css`.

- [ ] **Step 7: Write `site/src/styles.css`**

```css
@import "tailwindcss";

@theme {
  --color-bg: oklch(0.145 0.005 260);
  --color-surface: oklch(0.185 0.006 260);
  --color-line: oklch(0.26 0.008 260);
  --color-ink: oklch(0.96 0.003 260);
  --color-muted: oklch(0.72 0.008 260);
  --color-accent: oklch(0.78 0.13 180);

  --font-sans: "Inter Variable", ui-sans-serif, system-ui, sans-serif;
  --font-mono:
    "JetBrains Mono Variable", ui-monospace, SFMono-Regular, Menlo, monospace;

  --ease-out-quint: cubic-bezier(0.22, 1, 0.36, 1);
}

@layer base {
  html {
    scroll-behavior: smooth;
    -webkit-text-size-adjust: 100%;
  }

  body {
    background-color: var(--color-bg);
    color: var(--color-muted);
    font-family: var(--font-sans);
    font-synthesis-weight: none;
    text-rendering: optimizeLegibility;
  }

  h1,
  h2,
  h3 {
    color: var(--color-ink);
    text-wrap: balance;
  }

  p {
    text-wrap: pretty;
  }

  :focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 3px;
    border-radius: 2px;
  }

  ::selection {
    background: color-mix(in oklch, var(--color-accent) 30%, transparent);
    color: var(--color-ink);
  }
}

@layer components {
  .prose-measure {
    max-width: 68ch;
  }

  .will-reveal {
    opacity: 0;
    transform: translateY(12px);
  }

  .is-revealed {
    opacity: 1;
    transform: none;
    transition:
      opacity 620ms var(--ease-out-quint) var(--reveal-delay, 0ms),
      transform 620ms var(--ease-out-quint) var(--reveal-delay, 0ms);
  }
}

@media (prefers-reduced-motion: reduce) {
  html {
    scroll-behavior: auto;
  }

  .will-reveal {
    opacity: 1;
    transform: none;
  }

  .is-revealed {
    transition: opacity 120ms linear;
  }

  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd site && bun run test tests/tokens.test.ts`
Expected: PASS — 4 tests.

- [ ] **Step 9: Write `site/src/sections/index.ts`**

The array is empty until Task 3; the contract it publishes is what later tasks build against.

```typescript
export interface Section {
  readonly id: string;
  render(): string;
}

export const SECTIONS: readonly Section[] = [];
```

- [ ] **Step 10: Write `site/index.template.html`**

```html
<!doctype html>
<html lang="en" class="bg-bg">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>cloud-app — ship Azure infra without writing Terraform</title>
    <meta
      name="description"
      content="Describe an app in a small YAML manifest. A GitHub Action turns it into Terraform and deploys a full Azure stack: Container Apps, Key Vault, Postgres, private networking."
    />
    <meta name="color-scheme" content="dark" />
    <meta property="og:title" content="cloud-app" />
    <meta
      property="og:description"
      content="Ship Azure infra without writing Terraform. One manifest, one Action step, private by default."
    />
    <meta property="og:type" content="website" />
    <script type="module" src="/src/main.ts"></script>
  </head>
  <body class="min-h-dvh antialiased">
    <a
      href="#main"
      class="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-surface focus:px-4 focus:py-2 focus:text-ink"
      >Skip to content</a
    >
    <main id="main">
      <!--SECTIONS-->
    </main>
    <div
      class="sr-only"
      role="status"
      aria-live="polite"
      data-copy-status
    ></div>
  </body>
</html>
```

- [ ] **Step 11: Write `site/src/prerender.ts`**

```typescript
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { SECTIONS } from "./sections";

const MARKER = "<!--SECTIONS-->";

export function renderDocument(template: string): string {
  if (!template.includes(MARKER)) {
    throw new Error(`template is missing the ${MARKER} marker`);
  }
  return template.replace(
    MARKER,
    SECTIONS.map((section) => section.render()).join("\n"),
  );
}

export function prerenderToDisk(): void {
  const templatePath = fileURLToPath(
    new URL("../index.template.html", import.meta.url),
  );
  const outputPath = fileURLToPath(new URL("../index.html", import.meta.url));
  writeFileSync(outputPath, renderDocument(readFileSync(templatePath, "utf8")));
}

if (import.meta.main) {
  prerenderToDisk();
}
```

- [ ] **Step 12: Write `site/src/main.ts`**

Behaviour wiring lands in Tasks 4–7; this is the entry point that makes the build produce a bundle.

```typescript
import "./styles.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
```

- [ ] **Step 13: Write `site/vite.config.ts`**

```typescript
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import type { Plugin, ViteDevServer } from "vite";
import { defineConfig } from "vitest/config";
import tailwindcss from "@tailwindcss/vite";

const SECTION_SOURCES = [
  "/src/sections/",
  "/src/content.ts",
  "/index.template.html",
];

function prerenderSections(): Plugin {
  const run = () =>
    execFileSync(
      "bun",
      [fileURLToPath(new URL("./src/prerender.ts", import.meta.url))],
      {
        stdio: "inherit",
      },
    );

  return {
    name: "prerender-sections",
    buildStart() {
      run();
    },
    configureServer(server: ViteDevServer) {
      server.watcher.on("change", (file: string) => {
        if (SECTION_SOURCES.some((source) => file.includes(source))) {
          run();
          server.ws.send({ type: "full-reload" });
        }
      });
    },
  };
}

export default defineConfig({
  base: "/cloud-app/",
  plugins: [prerenderSections(), tailwindcss()],
  build: {
    target: "es2022",
    cssMinify: "lightningcss",
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
  },
});
```

`defineConfig` comes from `vitest/config`, not `vite` — that is what types the `test` block. Importing it from `vite` fails `tsc --noEmit` with "Object literal may only specify known properties, and 'test' does not exist".

- [ ] **Step 14: Verify the build produces a static page**

Run: `cd site && bun run build`
Expected: PASS — `tsc --noEmit` silent, Vite writes `dist/index.html` plus hashed CSS/JS assets.

Run: `grep -c 'SECTIONS' dist/index.html`
Expected: `0` — the marker was replaced, not shipped.

- [ ] **Step 15: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add site .gitignore
git commit -m "feat(site): scaffold vite + tailwind landing page with token contrast tests"
```

---

## Task 2: Content module and manifest-sample schema enforcement

**Files:**

- Create: `site/src/lib/html.ts`, `site/src/content.ts`
- Test: `site/tests/content.test.ts`

**Interfaces:**

- Consumes: nothing from Task 1 except the project layout.
- Produces:
  - `html(strings: TemplateStringsArray, ...values: unknown[]): string` and `escapeHtml(value: string): string` from `src/lib/html.ts`. `html` does **not** escape — it joins, flattening arrays. Callers pass user-visible code through `escapeHtml`.
  - From `src/content.ts`: `REPO_URL: string`, `DOCS: { usage: string; trust: string; license: string; repo: string }`, `interface CodeSample { id: string; filename: string; label: string; kind: 'manifest' | 'workflow'; code: string }`, `SAMPLES: readonly CodeSample[]`, and `sample(id: string): CodeSample`.

- [ ] **Step 1: Write the failing test — `site/tests/content.test.ts`**

```typescript
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { DOCS, REPO_URL, SAMPLES, sample } from "../src/content";

const schema = JSON.parse(
  readFileSync(
    fileURLToPath(
      new URL("../../terraform/schema/cloud-app.schema.json", import.meta.url),
    ),
    "utf8",
  ),
);

const validate = new Ajv2020({ strict: false, allErrors: true }).compile(
  schema,
);
const manifests = SAMPLES.filter((entry) => entry.kind === "manifest");

describe("code samples", () => {
  it("ships at least one manifest and one workflow sample", () => {
    expect(manifests.length).toBeGreaterThan(0);
    expect(SAMPLES.some((entry) => entry.kind === "workflow")).toBe(true);
  });

  it("gives every sample a unique id", () => {
    expect(new Set(SAMPLES.map((entry) => entry.id)).size).toBe(SAMPLES.length);
  });

  it.each(manifests)("$id validates against the platform schema", (entry) => {
    validate(parse(entry.code));
    expect(validate.errors ?? []).toEqual([]);
  });

  it("parses every workflow sample as YAML", () => {
    for (const entry of SAMPLES.filter((item) => item.kind === "workflow")) {
      expect(parse(entry.code)).toBeTypeOf("object");
    }
  });

  it("throws a useful error for an unknown sample id", () => {
    expect(() => sample("does-not-exist")).toThrow(/does-not-exist/);
  });
});

describe("documentation links", () => {
  it("derives every link from the repository constant", () => {
    for (const url of Object.values(DOCS)) {
      expect(url.startsWith(REPO_URL)).toBe(true);
    }
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd site && bun run test tests/content.test.ts`
Expected: FAIL — cannot resolve `../src/content`.

- [ ] **Step 3: Write `site/src/lib/html.ts`**

```typescript
const ENTITIES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ENTITIES[char] ?? char);
}

/**
 * Joins a template into markup. Values are inserted raw so sections can nest
 * each other's output; anything user-visible that is not markup (code samples,
 * copy) must be passed through escapeHtml by the caller.
 */
export function html(
  strings: TemplateStringsArray,
  ...values: unknown[]
): string {
  return strings.reduce<string>((out, chunk, index) => {
    if (index === 0) return chunk;
    const value = values[index - 1];
    return (
      out + (Array.isArray(value) ? value.join("") : String(value)) + chunk
    );
  }, "");
}
```

- [ ] **Step 4: Write `site/src/content.ts`**

Every manifest below was validated against `terraform/schema/cloud-app.schema.json` while writing this plan. Do not edit the YAML without re-running the test.

```typescript
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
  readonly kind: "manifest" | "workflow";
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd site && bun run test tests/content.test.ts`
Expected: PASS — every manifest sample validates, links derive from `REPO_URL`.

- [ ] **Step 6: Prove the test actually catches drift**

Temporarily change `name: orders-api` to `name: Orders_API` in `hero-manifest` (the schema requires `^[a-z][a-z0-9-]{1,29}$`).

Run: `cd site && bun run test tests/content.test.ts`
Expected: FAIL — an ajv error on `/name` `pattern`.

Revert the change and re-run.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add site/src/lib/html.ts site/src/content.ts site/tests/content.test.ts
git commit -m "feat(site): add typed content module with schema-validated manifest samples"
```

---

## Task 3: Hero section and static prerender

**Files:**

- Create: `site/src/sections/hero.ts`
- Modify: `site/src/sections/index.ts`
- Test: `site/tests/prerender.test.ts`, `site/tests/hero.test.ts`

**Interfaces:**

- Consumes: `Section` from `src/sections/index.ts`; `html`, `escapeHtml` from `src/lib/html.ts`; `DOCS`, `sample` from `src/content.ts`; `renderDocument` from `src/prerender.ts`.
- Produces: `hero: Section` from `src/sections/hero.ts`. Establishes the markup contracts later behaviours bind to: a tab group is `[data-tabs]` containing `[role="tab"]` buttons and `[role="tabpanel"]` panels; a copy button is `<button data-copy-target="<id of a <pre>">`; a reveal target is `[data-reveal]`.

- [ ] **Step 1: Write the failing prerender test — `site/tests/prerender.test.ts`**

```typescript
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { renderDocument } from "../src/prerender";
import { SECTIONS } from "../src/sections";

const template = readFileSync(
  fileURLToPath(new URL("../index.template.html", import.meta.url)),
  "utf8",
);

function documentFrom(markup: string): Document {
  return new DOMParser().parseFromString(markup, "text/html");
}

describe("renderDocument", () => {
  it("replaces the marker with section markup", () => {
    const output = renderDocument(template);
    expect(output).not.toContain("<!--SECTIONS-->");
    expect(output.length).toBeGreaterThan(template.length);
  });

  it("throws when the template has no marker", () => {
    expect(() => renderDocument("<html></html>")).toThrow(/marker/);
  });

  it("renders every registered section into main", () => {
    const doc = documentFrom(renderDocument(template));
    for (const section of SECTIONS) {
      const element = doc.getElementById(section.id);
      expect(
        element,
        `section #${section.id} is missing from the document`,
      ).not.toBeNull();
      expect(element?.closest("main")).not.toBeNull();
    }
  });

  it("has exactly one h1", () => {
    expect(
      documentFrom(renderDocument(template)).querySelectorAll("h1"),
    ).toHaveLength(1);
  });

  it("is readable without JavaScript — no section is hidden by a reveal class", () => {
    const doc = documentFrom(renderDocument(template));
    expect(doc.querySelectorAll(".will-reveal")).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Write the failing hero test — `site/tests/hero.test.ts`**

```typescript
import { describe, expect, it } from "vitest";
import { hero } from "../src/sections/hero";
import { DOCS, sample } from "../src/content";

function render(): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = hero.render();
  return host;
}

describe("hero section", () => {
  it("states the headline in the only h1", () => {
    const heading = render().querySelector("h1");
    expect(heading?.textContent).toContain("without writing Terraform");
  });

  it("links both calls to action at the documented URLs", () => {
    const hrefs = [...render().querySelectorAll("a")].map((link) =>
      link.getAttribute("href"),
    );
    expect(hrefs).toContain(DOCS.usage);
    expect(hrefs).toContain(DOCS.repo);
  });

  it("renders a tab group with one panel per sample and only the first visible", () => {
    const host = render();
    const tabs = host.querySelectorAll('[role="tab"]');
    const panels = host.querySelectorAll<HTMLElement>('[role="tabpanel"]');
    expect(tabs).toHaveLength(2);
    expect(panels).toHaveLength(2);
    expect(panels[0]?.hasAttribute("hidden")).toBe(false);
    expect(panels[1]?.hasAttribute("hidden")).toBe(true);
  });

  it("wires each tab to its panel with matching aria ids", () => {
    for (const tab of render().querySelectorAll('[role="tab"]')) {
      const panelId = tab.getAttribute("aria-controls");
      expect(panelId).toBeTruthy();
      expect(
        render().querySelector(`#${panelId}`)?.getAttribute("aria-labelledby"),
      ).toBe(tab.id);
    }
  });

  it("escapes the code sample rather than injecting it as markup", () => {
    const host = render();
    const code =
      host.querySelector("#panel-hero-manifest pre")?.textContent ?? "";
    expect(code).toBe(sample("hero-manifest").code);
  });

  it("hides copy buttons until JavaScript enables them", () => {
    for (const button of render().querySelectorAll("[data-copy-target]")) {
      expect(button.hasAttribute("hidden")).toBe(true);
    }
  });
});
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `cd site && bun run test tests/hero.test.ts tests/prerender.test.ts`
Expected: FAIL — cannot resolve `../src/sections/hero`.

- [ ] **Step 4: Write `site/src/sections/hero.ts`**

```typescript
import { html, escapeHtml } from "../lib/html";
import { DOCS, sample } from "../content";
import type { Section } from "./index";

const TABS = [sample("hero-manifest"), sample("hero-workflow")];

function codePanel(
  id: string,
  filename: string,
  code: string,
  active: boolean,
): string {
  return html`
    <div
      id="panel-${id}"
      role="tabpanel"
      aria-labelledby="tab-${id}"
      tabindex="0"
      ${active ? "" : "hidden"}
      class="relative"
    >
      <button
        type="button"
        hidden
        data-copy-target="code-${id}"
        class="absolute right-3 top-3 rounded-md border border-line bg-bg/80 px-2.5 py-1 font-mono text-xs text-muted transition-colors duration-150 hover:text-ink focus-visible:text-ink"
      >
        Copy
      </button>
      <pre
        id="code-${id}"
        class="overflow-x-auto px-5 py-5 font-mono text-[13px] leading-relaxed text-ink/90"
      ><code>${escapeHtml(code)}</code></pre>
      <p class="sr-only">${escapeHtml(filename)}</p>
    </div>
  `;
}

export const hero: Section = {
  id: "hero",
  render: () => html`
    <section id="hero" class="relative overflow-hidden border-b border-line">
      <div
        aria-hidden="true"
        class="pointer-events-none absolute inset-0 opacity-50 [background-image:linear-gradient(var(--color-line)_1px,transparent_1px),linear-gradient(90deg,var(--color-line)_1px,transparent_1px)] [background-size:56px_56px] [mask-image:radial-gradient(90%_60%_at_50%_0%,black,transparent)]"
      ></div>

      <div
        class="relative mx-auto w-full max-w-5xl px-6 pb-20 pt-20 md:pb-28 md:pt-28"
      >
        <p class="font-mono text-xs tracking-[0.14em] text-accent">
          AZURE · TERRAFORM · GITHUB ACTIONS
        </p>

        <h1
          class="mt-7 max-w-3xl text-[clamp(2.25rem,6vw,4.5rem)] font-semibold leading-[1.04] tracking-[-0.035em]"
        >
          Ship Azure infra without writing Terraform.
        </h1>

        <p class="prose-measure mt-6 text-lg leading-relaxed">
          Describe your app in a twelve-line manifest. One Action step turns it
          into a full stack — Container Apps, Key Vault, Postgres, private
          networking — and keeps it there.
        </p>

        <div class="mt-9 flex flex-wrap items-center gap-3">
          <a
            href="${DOCS.usage}"
            class="rounded-lg bg-ink px-5 py-2.5 text-sm font-semibold text-bg transition-transform duration-150 ease-[var(--ease-out-quint)] hover:-translate-y-0.5"
            >Get started</a
          >
          <a
            href="${DOCS.repo}"
            class="rounded-lg border border-line px-5 py-2.5 text-sm font-semibold text-ink transition-colors duration-150 hover:border-accent"
            >View on GitHub</a
          >
        </div>

        <div
          data-tabs
          class="mt-14 overflow-hidden rounded-xl border border-line bg-surface shadow-[0_24px_60px_-30px_rgb(0_0_0/0.9)]"
        >
          <div
            role="tablist"
            aria-label="Files you write"
            class="flex gap-1 border-b border-line px-2"
          >
            ${TABS.map(
              (entry, index) => html`
                <button
                  type="button"
                  role="tab"
                  id="tab-${entry.id}"
                  aria-controls="panel-${entry.id}"
                  aria-selected="${index === 0}"
                  tabindex="${index === 0 ? 0 : -1}"
                  class="-mb-px border-b px-3 py-2.5 font-mono text-xs transition-colors duration-150 aria-selected:border-accent aria-selected:text-accent border-transparent text-muted hover:text-ink"
                >
                  ${escapeHtml(entry.filename)}
                </button>
              `,
            )}
          </div>
          ${TABS.map((entry, index) =>
            codePanel(entry.id, entry.filename, entry.code, index === 0),
          )}
        </div>
      </div>
    </section>
  `,
};
```

- [ ] **Step 5: Register the section — modify `site/src/sections/index.ts`**

```typescript
import { hero } from "./hero";

export interface Section {
  readonly id: string;
  render(): string;
}

export const SECTIONS: readonly Section[] = [hero];
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd site && bun run test`
Expected: PASS — tokens, content, hero, and prerender suites all green.

- [ ] **Step 7: Verify the built page carries the hero without JavaScript**

Run: `cd site && bun run build && grep -c 'without writing Terraform' dist/index.html`
Expected: `1` — the headline is in the static HTML, not injected at runtime.

- [ ] **Step 8: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add site/src/sections site/tests/hero.test.ts site/tests/prerender.test.ts
git commit -m "feat(site): add hero section rendered into static HTML at build time"
```

---

## Task 4: Tabs behaviour

**Files:**

- Create: `site/src/behaviors/tabs.ts`
- Modify: `site/src/main.ts`
- Test: `site/tests/tabs.test.ts`

**Interfaces:**

- Consumes: the markup contract from Task 3 — `[data-tabs]` groups containing `[role="tab"]` buttons with `aria-controls`, and `[role="tabpanel"]` panels.
- Produces: `initTabs(root?: ParentNode): void` from `src/behaviors/tabs.ts`.

- [ ] **Step 1: Write the failing test — `site/tests/tabs.test.ts`**

```typescript
import { beforeEach, describe, expect, it } from "vitest";
import { initTabs } from "../src/behaviors/tabs";

function setup(): { tabs: HTMLButtonElement[]; panels: HTMLElement[] } {
  document.body.innerHTML = `
    <div data-tabs>
      <div role="tablist">
        <button type="button" role="tab" id="tab-a" aria-controls="panel-a" aria-selected="true" tabindex="0">A</button>
        <button type="button" role="tab" id="tab-b" aria-controls="panel-b" aria-selected="false" tabindex="-1">B</button>
      </div>
      <div id="panel-a" role="tabpanel" aria-labelledby="tab-a">first</div>
      <div id="panel-b" role="tabpanel" aria-labelledby="tab-b" hidden>second</div>
    </div>
  `;
  initTabs(document);
  return {
    tabs: [...document.querySelectorAll<HTMLButtonElement>('[role="tab"]')],
    panels: [...document.querySelectorAll<HTMLElement>('[role="tabpanel"]')],
  };
}

function press(tab: HTMLElement, key: string): void {
  tab.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
}

describe("initTabs", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("shows the panel of the clicked tab and hides the others", () => {
    const { tabs, panels } = setup();
    tabs[1]?.click();
    expect(panels[0]?.hidden).toBe(true);
    expect(panels[1]?.hidden).toBe(false);
    expect(tabs[1]?.getAttribute("aria-selected")).toBe("true");
    expect(tabs[0]?.getAttribute("aria-selected")).toBe("false");
  });

  it("keeps exactly one tab in the tab order", () => {
    const { tabs } = setup();
    tabs[1]?.click();
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([-1, 0]);
  });

  it("moves selection with ArrowRight and wraps around", () => {
    const { tabs, panels } = setup();
    press(tabs[0]!, "ArrowRight");
    expect(panels[1]?.hidden).toBe(false);
    press(tabs[1]!, "ArrowRight");
    expect(panels[0]?.hidden).toBe(false);
  });

  it("moves selection with ArrowLeft, Home, and End", () => {
    const { tabs, panels } = setup();
    press(tabs[0]!, "End");
    expect(panels[1]?.hidden).toBe(false);
    press(tabs[1]!, "Home");
    expect(panels[0]?.hidden).toBe(false);
    press(tabs[0]!, "ArrowLeft");
    expect(panels[1]?.hidden).toBe(false);
  });

  it("focuses the tab reached by keyboard but not the one reached by click", () => {
    const { tabs } = setup();
    press(tabs[0]!, "ArrowRight");
    expect(document.activeElement).toBe(tabs[1]);
    tabs[0]?.click();
    expect(document.activeElement).toBe(tabs[1]);
  });

  it("ignores unrelated keys", () => {
    const { tabs, panels } = setup();
    press(tabs[0]!, "a");
    expect(panels[0]?.hidden).toBe(false);
  });

  it("does nothing when there is no tab group", () => {
    document.body.innerHTML = "<div>no tabs here</div>";
    expect(() => initTabs(document)).not.toThrow();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd site && bun run test tests/tabs.test.ts`
Expected: FAIL — cannot resolve `../src/behaviors/tabs`.

- [ ] **Step 3: Write `site/src/behaviors/tabs.ts`**

```typescript
const KEY_DELTA: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1 };

export function initTabs(root: ParentNode = document): void {
  for (const group of root.querySelectorAll<HTMLElement>("[data-tabs]")) {
    setupGroup(group);
  }
}

function setupGroup(group: HTMLElement): void {
  const tabs = [...group.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  const panels = [...group.querySelectorAll<HTMLElement>('[role="tabpanel"]')];
  if (tabs.length === 0) return;

  const select = (index: number, moveFocus: boolean): void => {
    tabs.forEach((tab, position) => {
      const active = position === index;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active && moveFocus) tab.focus();
    });
    panels.forEach((panel, position) => {
      panel.hidden = position !== index;
    });
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => select(index, false));
    tab.addEventListener("keydown", (event) => {
      const target =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? tabs.length - 1
            : KEY_DELTA[event.key] === undefined
              ? -1
              : (index + KEY_DELTA[event.key]! + tabs.length) % tabs.length;
      if (target < 0) return;
      event.preventDefault();
      select(target, true);
    });
  });

  const selected = tabs.findIndex(
    (tab) => tab.getAttribute("aria-selected") === "true",
  );
  select(selected < 0 ? 0 : selected, false);
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd site && bun run test tests/tabs.test.ts`
Expected: PASS — 7 tests.

- [ ] **Step 5: Wire it up — modify `site/src/main.ts`**

```typescript
import "./styles.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { initTabs } from "./behaviors/tabs";

initTabs(document);
```

- [ ] **Step 6: Verify in the browser**

Run: `cd site && bun run dev`

Open the printed URL. Click both tabs in the hero panel, then focus a tab and press ArrowRight, ArrowLeft, Home, End. Each switches the visible file. Stop the dev server.

- [ ] **Step 7: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add site/src/behaviors/tabs.ts site/src/main.ts site/tests/tabs.test.ts
git commit -m "feat(site): add accessible tabs behaviour for the hero code panel"
```

---

## Task 5: Copy-to-clipboard behaviour

**Files:**

- Create: `site/src/behaviors/copy.ts`
- Modify: `site/src/main.ts`
- Test: `site/tests/copy.test.ts`

**Interfaces:**

- Consumes: `<button hidden data-copy-target="<element id>">` from Task 3, and the `[data-copy-status]` live region already present in `index.template.html`.
- Produces: `initCopy(root?: ParentNode, clipboard?: Pick<Clipboard, 'writeText'>): void` from `src/behaviors/copy.ts`. The `clipboard` parameter exists so tests can inject a stub; production callers omit it.

- [ ] **Step 1: Write the failing test — `site/tests/copy.test.ts`**

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initCopy } from "../src/behaviors/copy";

function setup(): { button: HTMLButtonElement; status: HTMLElement } {
  document.body.innerHTML = `
    <button type="button" hidden data-copy-target="code-a">Copy</button>
    <pre id="code-a">name: orders-api</pre>
    <div role="status" aria-live="polite" data-copy-status></div>
  `;
  return {
    button: document.querySelector("[data-copy-target]")!,
    status: document.querySelector("[data-copy-status]")!,
  };
}

describe("initCopy", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("reveals copy buttons that are hidden for non-JavaScript readers", () => {
    const { button } = setup();
    initCopy(document, { writeText: vi.fn().mockResolvedValue(undefined) });
    expect(button.hidden).toBe(false);
  });

  it("writes the target element text to the clipboard", async () => {
    const { button } = setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    initCopy(document, { writeText });
    button.click();
    await vi.waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("name: orders-api"),
    );
  });

  it("announces success in the live region and restores the label", async () => {
    const { button, status } = setup();
    initCopy(document, { writeText: vi.fn().mockResolvedValue(undefined) });
    button.click();
    await vi.waitFor(() => expect(status.textContent).toBe("Copied"));
    expect(button.textContent?.trim()).toBe("Copied");
    vi.advanceTimersByTime(2000);
    expect(button.textContent?.trim()).toBe("Copy");
    expect(status.textContent).toBe("");
  });

  it("announces a recoverable message when the clipboard rejects", async () => {
    const { button, status } = setup();
    initCopy(document, {
      writeText: vi.fn().mockRejectedValue(new Error("denied")),
    });
    button.click();
    await vi.waitFor(() =>
      expect(status.textContent).toMatch(/copy manually/i),
    );
  });

  it("ignores buttons whose target is missing", () => {
    document.body.innerHTML =
      '<button data-copy-target="nope" hidden>Copy</button>';
    const writeText = vi.fn();
    initCopy(document, { writeText });
    document.querySelector<HTMLButtonElement>("[data-copy-target]")?.click();
    expect(writeText).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd site && bun run test tests/copy.test.ts`
Expected: FAIL — cannot resolve `../src/behaviors/copy`.

- [ ] **Step 3: Write `site/src/behaviors/copy.ts`**

```typescript
const RESET_MS = 2000;
const FAILURE_MESSAGE = "Copy failed — select the code and copy manually";

export function initCopy(
  root: ParentNode = document,
  clipboard: Pick<Clipboard, "writeText"> = navigator.clipboard,
): void {
  const status = root.querySelector<HTMLElement>("[data-copy-status]");

  for (const button of root.querySelectorAll<HTMLButtonElement>(
    "[data-copy-target]",
  )) {
    const targetId = button.dataset.copyTarget;
    const target = targetId
      ? root.querySelector<HTMLElement>(`#${targetId}`)
      : null;
    if (!target) continue;

    button.hidden = false;
    const label = button.textContent ?? "Copy";
    let timer: ReturnType<typeof setTimeout> | undefined;

    button.addEventListener("click", () => {
      void clipboard
        .writeText(target.textContent ?? "")
        .then(() => announce("Copied"))
        .catch(() => announce(FAILURE_MESSAGE));
    });

    function announce(message: string): void {
      button.textContent = message === "Copied" ? "Copied" : "Failed";
      if (status) status.textContent = message;
      clearTimeout(timer);
      timer = setTimeout(() => {
        button.textContent = label;
        if (status) status.textContent = "";
      }, RESET_MS);
    }
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd site && bun run test tests/copy.test.ts`
Expected: PASS — 5 tests.

- [ ] **Step 5: Wire it up — modify `site/src/main.ts`**

```typescript
import "./styles.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { initTabs } from "./behaviors/tabs";
import { initCopy } from "./behaviors/copy";

initTabs(document);
initCopy(document);
```

- [ ] **Step 6: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add site/src/behaviors/copy.ts site/src/main.ts site/tests/copy.test.ts
git commit -m "feat(site): add copy-to-clipboard with a polite live region"
```

---

## Task 6: Scroll reveal behaviour

**Files:**

- Create: `site/src/behaviors/reveal.ts`
- Modify: `site/src/main.ts`
- Test: `site/tests/reveal.test.ts`

**Interfaces:**

- Consumes: `[data-reveal]` elements inside `<section>` elements. None exist yet in the hero; Tasks 7–9 add them.
- Produces: `initReveal(root?: ParentNode): void` from `src/behaviors/reveal.ts`. Adds `will-reveal` at init and `is-revealed` on intersection, sets `--reveal-delay` per element for in-section stagger.

- [ ] **Step 1: Write the failing test — `site/tests/reveal.test.ts`**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { initReveal } from "../src/behaviors/reveal";

type ObserverCallback = (
  entries: Array<{ target: Element; isIntersecting: boolean }>,
) => void;

function stubObserver(): { trigger: ObserverCallback; unobserved: Element[] } {
  const unobserved: Element[] = [];
  let callback: ObserverCallback = () => {};
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(handler: ObserverCallback) {
        callback = handler;
      }
      observe(): void {}
      unobserve(element: Element): void {
        unobserved.push(element);
      }
      disconnect(): void {}
    },
  );
  return { trigger: (entries) => callback(entries), unobserved };
}

function stubMatchMedia(reduced: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({ matches: reduced, addEventListener: vi.fn() }),
  );
}

function setup(): HTMLElement[] {
  document.body.innerHTML = `
    <section id="one">
      <div data-reveal>a</div>
      <div data-reveal>b</div>
    </section>
    <section id="two">
      <div data-reveal>c</div>
    </section>
  `;
  return [...document.querySelectorAll<HTMLElement>("[data-reveal]")];
}

describe("initReveal", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("adds the hidden state only from JavaScript, then reveals on intersection", () => {
    stubMatchMedia(false);
    const observer = stubObserver();
    const targets = setup();
    initReveal(document);

    expect(
      targets.every((element) => element.classList.contains("will-reveal")),
    ).toBe(true);
    observer.trigger([{ target: targets[0]!, isIntersecting: true }]);
    expect(targets[0]?.classList.contains("is-revealed")).toBe(true);
    expect(targets[1]?.classList.contains("is-revealed")).toBe(false);
  });

  it("stops observing an element once it has been revealed", () => {
    stubMatchMedia(false);
    const observer = stubObserver();
    const targets = setup();
    initReveal(document);
    observer.trigger([{ target: targets[0]!, isIntersecting: true }]);
    expect(observer.unobserved).toEqual([targets[0]]);
  });

  it("ignores entries that are not intersecting", () => {
    stubMatchMedia(false);
    const observer = stubObserver();
    const targets = setup();
    initReveal(document);
    observer.trigger([{ target: targets[0]!, isIntersecting: false }]);
    expect(targets[0]?.classList.contains("is-revealed")).toBe(false);
  });

  it("staggers delays within a section and restarts them in the next", () => {
    stubMatchMedia(false);
    stubObserver();
    const targets = setup();
    initReveal(document);
    expect(targets[0]?.style.getPropertyValue("--reveal-delay")).toBe("0ms");
    expect(targets[1]?.style.getPropertyValue("--reveal-delay")).toBe("60ms");
    expect(targets[2]?.style.getPropertyValue("--reveal-delay")).toBe("0ms");
  });

  it("reveals everything immediately when reduced motion is requested", () => {
    stubMatchMedia(true);
    stubObserver();
    const targets = setup();
    initReveal(document);
    expect(
      targets.every((element) => element.classList.contains("is-revealed")),
    ).toBe(true);
    expect(
      targets.some((element) => element.classList.contains("will-reveal")),
    ).toBe(false);
  });

  it("reveals everything when IntersectionObserver is unavailable", () => {
    stubMatchMedia(false);
    vi.stubGlobal("IntersectionObserver", undefined);
    const targets = setup();
    initReveal(document);
    expect(
      targets.every((element) => element.classList.contains("is-revealed")),
    ).toBe(true);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd site && bun run test tests/reveal.test.ts`
Expected: FAIL — cannot resolve `../src/behaviors/reveal`.

- [ ] **Step 3: Write `site/src/behaviors/reveal.ts`**

```typescript
const STAGGER_MS = 60;
const MAX_STAGGER_STEPS = 4;

export function initReveal(root: ParentNode = document): void {
  const targets = [...root.querySelectorAll<HTMLElement>("[data-reveal]")];
  if (targets.length === 0) return;

  applyStagger(root);

  const prefersReducedMotion =
    typeof matchMedia === "function" &&
    matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (prefersReducedMotion || typeof IntersectionObserver === "undefined") {
    for (const target of targets) target.classList.add("is-revealed");
    return;
  }

  for (const target of targets) target.classList.add("will-reveal");

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-revealed");
        observer.unobserve(entry.target);
      }
    },
    { rootMargin: "0px 0px -10% 0px", threshold: 0.1 },
  );

  for (const target of targets) observer.observe(target);
}

function applyStagger(root: ParentNode): void {
  for (const section of root.querySelectorAll("section")) {
    section
      .querySelectorAll<HTMLElement>("[data-reveal]")
      .forEach((element, index) => {
        const steps = Math.min(index, MAX_STAGGER_STEPS);
        element.style.setProperty("--reveal-delay", `${steps * STAGGER_MS}ms`);
      });
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd site && bun run test tests/reveal.test.ts`
Expected: PASS — 6 tests.

- [ ] **Step 5: Wire it up — modify `site/src/main.ts`**

```typescript
import "./styles.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { initTabs } from "./behaviors/tabs";
import { initCopy } from "./behaviors/copy";
import { initReveal } from "./behaviors/reveal";

initTabs(document);
initCopy(document);
initReveal(document);
```

- [ ] **Step 6: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add site/src/behaviors/reveal.ts site/src/main.ts site/tests/reveal.test.ts
git commit -m "feat(site): add reduced-motion-aware scroll reveals"
```

---

## Task 7: Manifest→stack section with connector lines

**Files:**

- Create: `site/src/sections/manifest-stack.ts`, `site/src/behaviors/connect.ts`
- Modify: `site/src/sections/index.ts`, `site/src/main.ts`, `site/src/styles.css`
- Test: `site/tests/manifest-stack.test.ts`, `site/tests/connect.test.ts`

**Interfaces:**

- Consumes: `Section`, `html`, `escapeHtml`, `sample`.
- Produces: `manifestStack: Section` from `src/sections/manifest-stack.ts`, and `initConnectors(root?: ParentNode): void` from `src/behaviors/connect.ts`. Markup contract: a `[data-connectors]` element containing an `<svg data-connector-canvas>`, source anchors `[data-connect-from="<target id>"]`, and target elements addressed by `id`.

- [ ] **Step 1: Write the failing section test — `site/tests/manifest-stack.test.ts`**

```typescript
import { describe, expect, it } from "vitest";
import { manifestStack } from "../src/sections/manifest-stack";
import { sample } from "../src/content";

function render(): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = manifestStack.render();
  return host;
}

describe("manifest→stack section", () => {
  it("renders the manifest sample verbatim", () => {
    const host = render();
    const lines = [...host.querySelectorAll("[data-manifest-line]")].map(
      (line) => line.textContent,
    );
    expect(lines.join("\n")).toBe(sample("stack-manifest").code.trimEnd());
  });

  it("points every connector source at an element that exists", () => {
    const host = render();
    const sources = [
      ...host.querySelectorAll<HTMLElement>("[data-connect-from]"),
    ];
    expect(sources.length).toBeGreaterThan(0);
    for (const source of sources) {
      expect(
        host.querySelector(`#${source.dataset.connectFrom}`),
      ).not.toBeNull();
    }
  });

  it("provides an svg canvas for the connector lines", () => {
    expect(
      render().querySelector("[data-connectors] svg[data-connector-canvas]"),
    ).not.toBeNull();
  });

  it("marks the resource list as reveal targets", () => {
    expect(render().querySelectorAll("[data-reveal]").length).toBeGreaterThan(
      0,
    );
  });

  it("describes the diagram for screen readers", () => {
    const host = render();
    const canvas = host.querySelector("[data-connector-canvas]");
    expect(canvas?.getAttribute("aria-hidden")).toBe("true");
    expect(host.querySelector("h2")?.textContent).toBeTruthy();
  });
});
```

- [ ] **Step 2: Write the failing behaviour test — `site/tests/connect.test.ts`**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { initConnectors } from "../src/behaviors/connect";

function rect(top: number, left = 0, width = 100, height = 20): DOMRect {
  return {
    top,
    left,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON: () => ({}),
  } as DOMRect;
}

function setup(): void {
  document.body.innerHTML = `
    <div data-connectors>
      <svg data-connector-canvas aria-hidden="true"></svg>
      <span data-connect-from="res-app">app:</span>
      <span data-connect-from="res-db">database:</span>
      <div id="res-app">Container App</div>
      <div id="res-db">Postgres</div>
    </div>
  `;
  const container = document.querySelector<HTMLElement>("[data-connectors]")!;
  container.getBoundingClientRect = () => rect(0, 0, 400, 200);
  document
    .querySelectorAll<HTMLElement>('[data-connect-from], [id^="res-"]')
    .forEach((element, index) => {
      element.getBoundingClientRect = () => rect(index * 40);
    });
}

describe("initConnectors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("draws one line per source anchor", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    expect(
      document.querySelectorAll("[data-connector-canvas] line"),
    ).toHaveLength(2);
  });

  it("gives each line finite coordinates derived from element positions", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    for (const line of document.querySelectorAll(
      "[data-connector-canvas] line",
    )) {
      for (const attribute of ["x1", "y1", "x2", "y2"]) {
        expect(Number.isFinite(Number(line.getAttribute(attribute)))).toBe(
          true,
        );
      }
    }
  });

  it("redraws on resize instead of appending duplicates", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    window.dispatchEvent(new Event("resize"));
    expect(
      document.querySelectorAll("[data-connector-canvas] line"),
    ).toHaveLength(2);
  });

  it("skips the drawing animation under reduced motion but still draws lines", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    const lines = document.querySelectorAll("[data-connector-canvas] line");
    expect(lines).toHaveLength(2);
    expect(lines[0]?.classList.contains("connector-draw")).toBe(false);
  });

  it("does nothing when the section is absent", () => {
    document.body.innerHTML = "<main></main>";
    expect(() => initConnectors(document)).not.toThrow();
  });
});
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `cd site && bun run test tests/manifest-stack.test.ts tests/connect.test.ts`
Expected: FAIL — modules do not exist.

- [ ] **Step 4: Write `site/src/behaviors/connect.ts`**

```typescript
const SVG_NS = "http://www.w3.org/2000/svg";

export function initConnectors(root: ParentNode = document): void {
  for (const container of root.querySelectorAll<HTMLElement>(
    "[data-connectors]",
  )) {
    const canvas = container.querySelector<SVGSVGElement>(
      "[data-connector-canvas]",
    );
    if (!canvas) continue;

    const draw = (): void => {
      const frame = container.getBoundingClientRect();
      canvas.setAttribute("viewBox", `0 0 ${frame.width} ${frame.height}`);
      canvas.replaceChildren();

      const animate =
        typeof matchMedia !== "function" ||
        !matchMedia("(prefers-reduced-motion: reduce)").matches;

      for (const source of container.querySelectorAll<HTMLElement>(
        "[data-connect-from]",
      )) {
        const target = source.dataset.connectFrom
          ? container.querySelector<HTMLElement>(
              `#${source.dataset.connectFrom}`,
            )
          : null;
        if (!target) continue;

        const from = source.getBoundingClientRect();
        const to = target.getBoundingClientRect();
        const line = document.createElementNS(SVG_NS, "line");
        line.setAttribute("x1", String(from.right - frame.left));
        line.setAttribute("y1", String(from.top + from.height / 2 - frame.top));
        line.setAttribute("x2", String(to.left - frame.left));
        line.setAttribute("y2", String(to.top + to.height / 2 - frame.top));
        line.setAttribute(
          "class",
          animate ? "connector connector-draw" : "connector",
        );
        canvas.append(line);
      }
    };

    draw();
    window.addEventListener("resize", draw, { passive: true });
  }
}
```

- [ ] **Step 5: Add connector styles to `site/src/styles.css`**

Append inside the existing `@layer components` block:

```css
.connector {
  stroke: var(--color-line);
  stroke-width: 1;
}

.connector-draw {
  stroke-dasharray: 240;
  stroke-dashoffset: 240;
  animation: connector-draw 900ms var(--ease-out-quint) forwards;
}

@keyframes connector-draw {
  to {
    stroke-dashoffset: 0;
  }
}
```

And inside the existing `@media (prefers-reduced-motion: reduce)` block:

```css
.connector-draw {
  stroke-dashoffset: 0;
  animation: none;
}
```

- [ ] **Step 6: Write `site/src/sections/manifest-stack.ts`**

```typescript
import { html, escapeHtml } from "../lib/html";
import { sample } from "../content";
import type { Section } from "./index";

interface Resource {
  readonly id: string;
  readonly title: string;
  readonly detail: string;
}

const RESOURCES: readonly Resource[] = [
  {
    id: "res-app",
    title: "Container App",
    detail: "revision, scaling rules, internal ingress",
  },
  {
    id: "res-identity",
    title: "Managed identity",
    detail: "per-app, RG-scoped, federated to your workflow",
  },
  {
    id: "res-vault",
    title: "Key Vault",
    detail: "secrets synced from the workflow, referenced by the app",
  },
  {
    id: "res-db",
    title: "Postgres flexible server",
    detail: "private endpoint, private DNS, generated credentials",
  },
];

/** Manifest lines that anchor a connector, keyed by the resource they create. */
const ANCHORS: Record<string, string> = {
  "app:": "res-app",
  "  ingress: internal": "res-identity",
  "database:": "res-db",
  "  size: small": "res-vault",
};

function manifestLine(line: string): string {
  const target = ANCHORS[line];
  const attribute = target ? ` data-connect-from="${target}"` : "";
  return html`<span
    data-manifest-line
    class="block whitespace-pre${target ? " text-ink" : ""}"
    ${attribute}
    >${escapeHtml(line)}</span
  >`;
}

export const manifestStack: Section = {
  id: "manifest-stack",
  render: () => {
    const lines = sample("stack-manifest").code.trimEnd().split("\n");
    return html`
      <section id="manifest-stack" class="border-b border-line">
        <div class="mx-auto w-full max-w-5xl px-6 py-20 md:py-28">
          <h2
            class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
          >
            Twelve lines in. A whole stack out.
          </h2>
          <p class="prose-measure mt-4 text-base leading-relaxed">
            The manifest is the only thing you maintain. Everything on the right
            is generated, wired together, and reconciled on every deploy.
          </p>

          <div
            data-connectors
            class="relative mt-12 grid gap-8 md:grid-cols-2 md:gap-16"
          >
            <svg
              data-connector-canvas
              aria-hidden="true"
              class="pointer-events-none absolute inset-0 hidden h-full w-full md:block"
            ></svg>

            <div
              data-reveal
              class="relative rounded-xl border border-line bg-surface p-5 font-mono text-[13px] leading-relaxed text-muted"
            >
              ${lines.map(manifestLine)}
            </div>

            <ul class="relative space-y-3">
              ${RESOURCES.map(
                (resource) => html`
                  <li
                    id="${resource.id}"
                    data-reveal
                    class="rounded-lg border border-line bg-surface/60 px-4 py-3"
                  >
                    <p class="text-sm font-semibold text-ink">
                      ${escapeHtml(resource.title)}
                    </p>
                    <p class="mt-1 text-sm">${escapeHtml(resource.detail)}</p>
                  </li>
                `,
              )}
            </ul>
          </div>
        </div>
      </section>
    `;
  },
};
```

- [ ] **Step 7: Register and wire — modify `site/src/sections/index.ts` and `site/src/main.ts`**

`src/sections/index.ts`:

```typescript
import { hero } from "./hero";
import { manifestStack } from "./manifest-stack";

export interface Section {
  readonly id: string;
  render(): string;
}

export const SECTIONS: readonly Section[] = [hero, manifestStack];
```

`src/main.ts` — add the import and the call:

```typescript
import { initConnectors } from "./behaviors/connect";

initConnectors(document);
```

- [ ] **Step 8: Run the full suite**

Run: `cd site && bun run test`
Expected: PASS — all suites green.

- [ ] **Step 9: Verify the diagram in the browser**

Run: `cd site && bun run dev`

At a desktop width the four connector lines draw from the manifest to the resource list on first scroll into view. Narrow the window below 768px: the lines disappear and the two columns stack. Enable "Reduce motion" in the OS and reload: the lines are present immediately, undrawn. Stop the dev server.

- [ ] **Step 10: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add site/src site/tests/manifest-stack.test.ts site/tests/connect.test.ts
git commit -m "feat(site): add manifest-to-stack section with animated connectors"
```

---

## Task 8: How it works, capabilities, and environments sections

**Files:**

- Create: `site/src/sections/how-it-works.ts`, `site/src/sections/capabilities.ts`, `site/src/sections/environments.ts`
- Modify: `site/src/sections/index.ts`
- Test: `site/tests/sections-middle.test.ts`

**Interfaces:**

- Consumes: `Section`, `html`, `escapeHtml`, `sample`.
- Produces: `howItWorks: Section`, `capabilities: Section`, `environments: Section`.

- [ ] **Step 1: Write the failing test — `site/tests/sections-middle.test.ts`**

```typescript
import { describe, expect, it } from "vitest";
import { howItWorks } from "../src/sections/how-it-works";
import { capabilities } from "../src/sections/capabilities";
import { environments } from "../src/sections/environments";
import { sample } from "../src/content";

function render(markup: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = markup;
  return host;
}

describe("how it works", () => {
  it("presents exactly three ordered steps", () => {
    const host = render(howItWorks.render());
    expect(host.querySelectorAll("ol > li")).toHaveLength(3);
  });

  it("is the only section allowed to number itself", () => {
    expect(render(howItWorks.render()).querySelector("ol")).not.toBeNull();
  });

  it("names the plan-on-PR, apply-on-main split", () => {
    expect(render(howItWorks.render()).textContent).toMatch(/pull request/i);
  });
});

describe("capabilities", () => {
  it("lists compute and shared services as description groups, not cards", () => {
    const host = render(capabilities.render());
    expect(host.querySelectorAll("dl").length).toBeGreaterThan(0);
    expect(host.querySelectorAll("dt").length).toBeGreaterThanOrEqual(6);
  });

  it("names every compute type the platform supports", () => {
    const text = render(capabilities.render()).textContent ?? "";
    for (const compute of ["Container Apps", "Functions", "Static Web Apps"]) {
      expect(text).toContain(compute);
    }
  });
});

describe("environments", () => {
  it("shows the environments manifest sample verbatim", () => {
    const host = render(environments.render());
    expect(host.querySelector("pre")?.textContent).toBe(
      sample("environments-manifest").code,
    );
  });

  it("offers a copy button pointing at that sample", () => {
    const host = render(environments.render());
    const button = host.querySelector<HTMLElement>("[data-copy-target]");
    expect(button?.hasAttribute("hidden")).toBe(true);
    expect(host.querySelector(`#${button?.dataset.copyTarget}`)).not.toBeNull();
  });
});

describe("all three sections", () => {
  const sections = [howItWorks, capabilities, environments];

  it("uses h2 for its own heading and never h1", () => {
    for (const section of sections) {
      const host = render(section.render());
      expect(host.querySelectorAll("h1")).toHaveLength(0);
      expect(host.querySelectorAll("h2")).toHaveLength(1);
    }
  });

  it("marks content as reveal targets", () => {
    for (const section of sections) {
      expect(
        render(section.render()).querySelectorAll("[data-reveal]").length,
      ).toBeGreaterThan(0);
    }
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd site && bun run test tests/sections-middle.test.ts`
Expected: FAIL — modules do not exist.

- [ ] **Step 3: Write `site/src/sections/how-it-works.ts`**

```typescript
import { html, escapeHtml } from "../lib/html";
import type { Section } from "./index";

interface Step {
  readonly title: string;
  readonly body: string;
}

const STEPS: readonly Step[] = [
  {
    title: "Write the manifest",
    body: "A cloud-app.yml at the root of your repo names the app, its port, and whatever it needs — a database, storage, a second container.",
  },
  {
    title: "Add one step to your workflow",
    body: "The composite action runs inside your own gated job, under your environment protection rules and your OIDC federation.",
  },
  {
    title: "Pull requests plan, main applies",
    body: "Every pull request posts a Terraform plan. Merging to main applies it under a resource-group-scoped identity.",
  },
];

export const howItWorks: Section = {
  id: "how-it-works",
  render: () => html`
    <section id="how-it-works" class="border-b border-line">
      <div class="mx-auto w-full max-w-5xl px-6 py-20 md:py-28">
        <h2
          class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
        >
          Three steps, then it is just your pipeline.
        </h2>

        <ol class="mt-12 grid gap-10 md:grid-cols-3">
          ${STEPS.map(
            (step, index) => html`
              <li data-reveal class="border-t border-line pt-5">
                <span class="font-mono text-sm text-accent">0${index + 1}</span>
                <h3 class="mt-3 text-lg font-semibold">
                  ${escapeHtml(step.title)}
                </h3>
                <p class="mt-2 text-sm leading-relaxed">
                  ${escapeHtml(step.body)}
                </p>
              </li>
            `,
          )}
        </ol>
      </div>
    </section>
  `,
};
```

- [ ] **Step 4: Write `site/src/sections/capabilities.ts`**

```typescript
import { html, escapeHtml } from "../lib/html";
import type { Section } from "./index";

interface Entry {
  readonly term: string;
  readonly detail: string;
}

interface Group {
  readonly title: string;
  readonly entries: readonly Entry[];
}

const GROUPS: readonly Group[] = [
  {
    title: "Compute",
    entries: [
      {
        term: "Container Apps",
        detail:
          "one app or many, multi-container templates, public / internal / no ingress",
      },
      {
        term: "Functions",
        detail:
          "a container by default, or application code on dotnet-isolated, node, python, java, powershell",
      },
      {
        term: "Static Web Apps",
        detail:
          "built assets served from the same manifest and the same pipeline",
      },
    ],
  },
  {
    title: "Shared services",
    entries: [
      {
        term: "Key Vault",
        detail:
          "per-stack vault; workflow secrets synced in, referenced by every app",
      },
      {
        term: "Postgres or SQL Server",
        detail:
          "sized by keyword, one database or a map of them, per-app opt-in",
      },
      {
        term: "Blob storage",
        detail:
          "named containers with private endpoints and generated connection settings",
      },
      {
        term: "Private networking",
        detail:
          "private endpoints and private DNS by default; public access is an explicit opt-out",
      },
    ],
  },
];

export const capabilities: Section = {
  id: "capabilities",
  render: () => html`
    <section id="capabilities" class="border-b border-line">
      <div class="mx-auto w-full max-w-5xl px-6 py-20 md:py-28">
        <h2
          class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
        >
          What the manifest can ask for.
        </h2>

        <div class="mt-12 grid gap-12 md:grid-cols-2">
          ${GROUPS.map(
            (group) => html`
              <div data-reveal>
                <h3 class="font-mono text-sm text-accent">
                  ${escapeHtml(group.title)}
                </h3>
                <dl class="mt-5 divide-y divide-line border-t border-line">
                  ${group.entries.map(
                    (entry) => html`
                      <div class="py-4">
                        <dt class="text-base font-semibold text-ink">
                          ${escapeHtml(entry.term)}
                        </dt>
                        <dd class="mt-1 text-sm leading-relaxed">
                          ${escapeHtml(entry.detail)}
                        </dd>
                      </div>
                    `,
                  )}
                </dl>
              </div>
            `,
          )}
        </div>
      </div>
    </section>
  `,
};
```

- [ ] **Step 5: Write `site/src/sections/environments.ts`**

```typescript
import { html, escapeHtml } from "../lib/html";
import { sample } from "../content";
import type { Section } from "./index";

const MANIFEST = sample("environments-manifest");

export const environments: Section = {
  id: "environments",
  render: () => html`
    <section id="environments" class="border-b border-line">
      <div class="mx-auto w-full max-w-5xl px-6 py-20 md:py-28">
        <h2
          class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
        >
          One manifest. Every environment.
        </h2>
        <p class="prose-measure mt-4 text-base leading-relaxed">
          Environment blocks deep-merge over the base. Dev inherits everything;
          prod overrides only what differs. There is no second file to keep in
          sync and no copy to drift.
        </p>

        <div
          data-reveal
          class="relative mt-10 overflow-hidden rounded-xl border border-line bg-surface"
        >
          <button
            type="button"
            hidden
            data-copy-target="code-${MANIFEST.id}"
            class="absolute right-3 top-3 rounded-md border border-line bg-bg/80 px-2.5 py-1 font-mono text-xs text-muted transition-colors duration-150 hover:text-ink"
          >
            Copy
          </button>
          <pre
            id="code-${MANIFEST.id}"
            class="overflow-x-auto px-5 py-5 font-mono text-[13px] leading-relaxed text-ink/90"
          ><code>${escapeHtml(MANIFEST.code)}</code></pre>
        </div>

        <p data-reveal class="prose-measure mt-6 text-sm leading-relaxed">
          Deploying <span class="font-mono text-ink">prod</span> resolves
          <span class="font-mono text-ink">database.size</span> to
          <span class="font-mono text-ink">medium</span>; everything else comes
          from the base document unchanged.
        </p>
      </div>
    </section>
  `,
};
```

- [ ] **Step 6: Register the sections — modify `site/src/sections/index.ts`**

```typescript
import { hero } from "./hero";
import { manifestStack } from "./manifest-stack";
import { howItWorks } from "./how-it-works";
import { capabilities } from "./capabilities";
import { environments } from "./environments";

export interface Section {
  readonly id: string;
  render(): string;
}

export const SECTIONS: readonly Section[] = [
  hero,
  manifestStack,
  howItWorks,
  capabilities,
  environments,
];
```

- [ ] **Step 7: Run the full suite**

Run: `cd site && bun run test`
Expected: PASS — including the prerender suite, which now checks five section ids.

- [ ] **Step 8: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add site/src/sections site/tests/sections-middle.test.ts
git commit -m "feat(site): add how-it-works, capabilities, and environments sections"
```

---

## Task 9: Escape hatch, trust model, and quickstart sections

**Files:**

- Create: `site/src/sections/escape-hatch.ts`, `site/src/sections/security.ts`, `site/src/sections/quickstart.ts`
- Modify: `site/src/sections/index.ts`
- Test: `site/tests/sections-tail.test.ts`

**Interfaces:**

- Consumes: `Section`, `html`, `escapeHtml`, `sample`, `DOCS`.
- Produces: `escapeHatch: Section`, `security: Section`, `quickstart: Section`. `quickstart` renders the page footer inside its own `<section>`; there is no separate footer module.

- [ ] **Step 1: Write the failing test — `site/tests/sections-tail.test.ts`**

```typescript
import { describe, expect, it } from "vitest";
import { escapeHatch } from "../src/sections/escape-hatch";
import { security } from "../src/sections/security";
import { quickstart } from "../src/sections/quickstart";
import { DOCS, sample } from "../src/content";

function render(markup: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = markup;
  return host;
}

describe("escape hatch", () => {
  it("shows the custom terraform manifest sample verbatim", () => {
    expect(render(escapeHatch.render()).querySelector("pre")?.textContent).toBe(
      sample("custom-terraform-manifest").code,
    );
  });

  it("states the guardrail, not just the feature", () => {
    expect(render(escapeHatch.render()).textContent).toMatch(/resource group/i);
  });
});

describe("trust model", () => {
  it("lists the security properties as a description list", () => {
    expect(
      render(security.render()).querySelectorAll("dt").length,
    ).toBeGreaterThanOrEqual(4);
  });

  it("links the trust-modes documentation", () => {
    const hrefs = [...render(security.render()).querySelectorAll("a")].map(
      (a) => a.getAttribute("href"),
    );
    expect(hrefs).toContain(DOCS.trust);
  });
});

describe("quickstart and footer", () => {
  it("renders both files with their own copy buttons", () => {
    const host = render(quickstart.render());
    const buttons = [
      ...host.querySelectorAll<HTMLElement>("[data-copy-target]"),
    ];
    expect(buttons).toHaveLength(2);
    for (const button of buttons) {
      expect(button.hasAttribute("hidden")).toBe(true);
      expect(
        host.querySelector(`#${button.dataset.copyTarget}`),
      ).not.toBeNull();
    }
  });

  it("links usage, trust, repository, and license", () => {
    const hrefs = [...render(quickstart.render()).querySelectorAll("a")].map(
      (a) => a.getAttribute("href"),
    );
    for (const url of [DOCS.usage, DOCS.trust, DOCS.repo, DOCS.license]) {
      expect(hrefs).toContain(url);
    }
  });

  it("contains the page footer", () => {
    expect(render(quickstart.render()).querySelector("footer")).not.toBeNull();
  });
});

describe("all three sections", () => {
  it("uses exactly one h2 each and no h1", () => {
    for (const section of [escapeHatch, security, quickstart]) {
      const host = render(section.render());
      expect(host.querySelectorAll("h1")).toHaveLength(0);
      expect(host.querySelectorAll("h2")).toHaveLength(1);
    }
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd site && bun run test tests/sections-tail.test.ts`
Expected: FAIL — modules do not exist.

- [ ] **Step 3: Write `site/src/sections/escape-hatch.ts`**

```typescript
import { html, escapeHtml } from "../lib/html";
import { sample } from "../content";
import type { Section } from "./index";

const MANIFEST = sample("custom-terraform-manifest");

export const escapeHatch: Section = {
  id: "escape-hatch",
  render: () => html`
    <section id="escape-hatch" class="border-b border-line">
      <div
        class="mx-auto grid w-full max-w-5xl gap-10 px-6 py-20 md:grid-cols-2 md:items-center md:py-28"
      >
        <div data-reveal>
          <h2
            class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
          >
            When the platform does not model it, write it yourself.
          </h2>
          <p class="prose-measure mt-4 text-base leading-relaxed">
            Point <span class="font-mono text-ink">terraform:</span> at a
            directory of <span class="font-mono text-ink">*.tf</span> in your
            repo. It merges into a custom child module that receives platform
            context — resource group, subnets, Key Vault, per-app identity
            principal ids — and applies under the same resource-group-scoped
            identity as everything else.
          </p>
          <p class="prose-measure mt-4 text-sm leading-relaxed">
            The guardrail is the point: custom resources stay confined to your
            resource group for Azure resource-plane providers, and extra
            providers come from a fixed allowlist.
          </p>
        </div>

        <div
          data-reveal
          class="overflow-hidden rounded-xl border border-line bg-surface"
        >
          <pre
            id="code-${MANIFEST.id}"
            class="overflow-x-auto px-5 py-5 font-mono text-[13px] leading-relaxed text-ink/90"
          ><code>${escapeHtml(MANIFEST.code)}</code></pre>
        </div>
      </div>
    </section>
  `,
};
```

- [ ] **Step 4: Write `site/src/sections/security.ts`**

```typescript
import { html, escapeHtml } from "../lib/html";
import { DOCS } from "../content";
import type { Section } from "./index";

interface Property {
  readonly term: string;
  readonly detail: string;
}

const PROPERTIES: readonly Property[] = [
  {
    term: "Private by default",
    detail:
      "private endpoints and private DNS for data services; public ingress is an explicit opt-in per app",
  },
  {
    term: "Resource-group-scoped identities",
    detail:
      "the deploy identity for a stack can only touch that stack’s resource group",
  },
  {
    term: "OIDC federation, no stored credentials",
    detail:
      "the workflow exchanges a short-lived token; there is no service principal secret to rotate",
  },
  {
    term: "Plan on pull requests, apply on main",
    detail:
      "every change is reviewable as a Terraform plan before anything is applied",
  },
  {
    term: "Per-stack state isolation",
    detail:
      "each stack gets its own state container, so one repo can never read or write another’s state",
  },
];

export const security: Section = {
  id: "security",
  render: () => html`
    <section id="security" class="border-b border-line">
      <div class="mx-auto w-full max-w-5xl px-6 py-20 md:py-28">
        <h2
          class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
        >
          The parts a platform team asks about first.
        </h2>

        <dl data-reveal class="mt-12 divide-y divide-line border-y border-line">
          ${PROPERTIES.map(
            (property) => html`
              <div
                class="grid gap-2 py-5 md:grid-cols-[minmax(0,18rem)_1fr] md:gap-8"
              >
                <dt class="text-base font-semibold text-ink">
                  ${escapeHtml(property.term)}
                </dt>
                <dd class="text-sm leading-relaxed">
                  ${escapeHtml(property.detail)}
                </dd>
              </div>
            `,
          )}
        </dl>

        <p data-reveal class="mt-8 text-sm">
          <a
            href="${DOCS.trust}"
            class="text-accent underline underline-offset-4"
            >Read the trust and identity model</a
          >
        </p>
      </div>
    </section>
  `,
};
```

- [ ] **Step 5: Write `site/src/sections/quickstart.ts`**

```typescript
import { html, escapeHtml } from "../lib/html";
import { DOCS, sample } from "../content";
import type { Section } from "./index";

const FILES = [sample("hero-manifest"), sample("hero-workflow")];

function file(id: string, filename: string, code: string): string {
  return html`
    <div
      data-reveal
      class="relative overflow-hidden rounded-xl border border-line bg-surface"
    >
      <div
        class="flex items-center justify-between border-b border-line px-4 py-2.5"
      >
        <span class="font-mono text-xs text-muted"
          >${escapeHtml(filename)}</span
        >
        <button
          type="button"
          hidden
          data-copy-target="quickstart-${id}"
          class="rounded-md border border-line px-2.5 py-1 font-mono text-xs text-muted transition-colors duration-150 hover:text-ink"
        >
          Copy
        </button>
      </div>
      <pre
        id="quickstart-${id}"
        class="overflow-x-auto px-5 py-5 font-mono text-[13px] leading-relaxed text-ink/90"
      ><code>${escapeHtml(code)}</code></pre>
    </div>
  `;
}

export const quickstart: Section = {
  id: "quickstart",
  render: () => html`
    <section id="quickstart">
      <div class="mx-auto w-full max-w-5xl px-6 py-20 md:py-28">
        <h2
          class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
        >
          Two files. That is the whole onboarding.
        </h2>
        <p class="prose-measure mt-4 text-base leading-relaxed">
          Copy both into your repository, set the app id and private key
          secrets, and open a pull request. The plan tells you what you are
          about to get.
        </p>

        <div class="mt-10 grid gap-6 lg:grid-cols-2">
          ${FILES.map((entry) => file(entry.id, entry.filename, entry.code))}
        </div>

        <p data-reveal class="mt-10">
          <a
            href="${DOCS.usage}"
            class="inline-block rounded-lg bg-ink px-5 py-2.5 text-sm font-semibold text-bg transition-transform duration-150 ease-[var(--ease-out-quint)] hover:-translate-y-0.5"
            >Read the full manifest reference</a
          >
        </p>
      </div>

      <footer class="border-t border-line">
        <div
          class="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-sm"
        >
          <p class="font-mono text-xs text-muted">cloud-app</p>
          <nav class="flex flex-wrap gap-5">
            <a href="${DOCS.usage}" class="hover:text-ink">Usage</a>
            <a href="${DOCS.trust}" class="hover:text-ink">Trust model</a>
            <a href="${DOCS.repo}" class="hover:text-ink">GitHub</a>
            <a href="${DOCS.license}" class="hover:text-ink">MIT license</a>
          </nav>
        </div>
      </footer>
    </section>
  `,
};
```

- [ ] **Step 6: Register the sections — modify `site/src/sections/index.ts`**

```typescript
import { hero } from "./hero";
import { manifestStack } from "./manifest-stack";
import { howItWorks } from "./how-it-works";
import { capabilities } from "./capabilities";
import { environments } from "./environments";
import { escapeHatch } from "./escape-hatch";
import { security } from "./security";
import { quickstart } from "./quickstart";

export interface Section {
  readonly id: string;
  render(): string;
}

export const SECTIONS: readonly Section[] = [
  hero,
  manifestStack,
  howItWorks,
  capabilities,
  environments,
  escapeHatch,
  security,
  quickstart,
];
```

- [ ] **Step 7: Run the full suite and build**

Run: `cd site && bun run test && bun run build`
Expected: PASS — all eight sections render; `dist/index.html` contains all eight ids.

Run: `cd site && grep -o 'id="[a-z-]*"' dist/index.html | sort -u | head -20`
Expected: includes `id="hero"`, `id="manifest-stack"`, `id="how-it-works"`, `id="capabilities"`, `id="environments"`, `id="escape-hatch"`, `id="security"`, `id="quickstart"`.

- [ ] **Step 8: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add site/src/sections site/tests/sections-tail.test.ts
git commit -m "feat(site): add escape hatch, trust model, and quickstart sections"
```

---

## Task 10: GitHub Pages build and deploy workflow

**Files:**

- Create: `.github/workflows/site.yml`
- Modify: `sonar-project.properties`

**Interfaces:**

- Consumes: `site/package.json` scripts `test` and `build` from Task 1.
- Produces: a `site` workflow that builds on every pull request touching `site/**` and publishes to GitHub Pages on pushes to `main`.

- [ ] **Step 1: Resolve the action SHAs**

This repository pins every action to a commit SHA. Collect the four SHAs you need:

```bash
gh api repos/actions/checkout/commits/v4 --jq .sha
gh api repos/oven-sh/setup-bun/commits/v2 --jq .sha
gh api repos/actions/upload-pages-artifact/commits/v3 --jq .sha
gh api repos/actions/deploy-pages/commits/v4 --jq .sha
```

Keep the four values; each replaces the corresponding `PASTE_SHA_*` token in the next step. Leaving any token in place is a failure — actionlint will not catch it, but the workflow will not run.

- [ ] **Step 2: Write `.github/workflows/site.yml`**

```yaml
name: site

on:
  push:
    branches: [main]
    paths: ["site/**", ".github/workflows/site.yml"]
  pull_request:
    paths: ["site/**", ".github/workflows/site.yml"]

permissions:
  contents: read

concurrency:
  group: site-${{ github.ref }}
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@PASTE_SHA_CHECKOUT # v4

      - uses: oven-sh/setup-bun@PASTE_SHA_SETUP_BUN # v2
        with:
          bun-version: "1.3.14"

      - name: Install dependencies
        working-directory: site
        run: bun install --frozen-lockfile

      - name: Test
        working-directory: site
        run: bun run test

      - name: Build
        working-directory: site
        run: bun run build

      - name: Upload Pages artifact
        if: github.ref == 'refs/heads/main' && github.event_name == 'push'
        uses: actions/upload-pages-artifact@PASTE_SHA_UPLOAD # v3
        with:
          path: site/dist

  deploy:
    needs: build
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@PASTE_SHA_DEPLOY # v4
```

- [ ] **Step 3: Replace the SHA tokens**

Substitute each `PASTE_SHA_*` with the matching value from Step 1, keeping the `# v4` / `# v2` trailing comments.

Run: `grep -c PASTE_SHA .github/workflows/site.yml`
Expected: `0`.

- [ ] **Step 4: Lint the workflow**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
curl -sSL -o /tmp/actionlint.tar.gz \
  "https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_$(uname -s | tr '[:upper:]' '[:lower:]')_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').tar.gz"
tar xzf /tmp/actionlint.tar.gz -C /tmp actionlint
/tmp/actionlint .github/workflows/site.yml
```

Expected: no output — actionlint reports nothing.

- [ ] **Step 5: Exclude the site from Sonar analysis**

Read `sonar-project.properties`. If it has a `sonar.exclusions` key, append `,site/dist/**,site/node_modules/**` to its value. If it has no such key, add this line:

```properties
sonar.exclusions=site/dist/**,site/node_modules/**
```

- [ ] **Step 6: Verify the lockfile is committed**

Run: `git status --short site/bun.lock`
Expected: the lockfile is tracked (either already committed or staged now). `bun install --frozen-lockfile` fails in CI without it.

- [ ] **Step 7: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add .github/workflows/site.yml sonar-project.properties site/bun.lock
git commit -m "ci(site): build the landing page on pull requests and publish to GitHub Pages"
```

- [ ] **Step 8: Enable Pages (one-time, manual)**

In the repository settings, set Pages → Build and deployment → Source to **GitHub Actions**. Without this the deploy job fails with `Resource not accessible by integration`.

---

## Task 11: Verification pass and README link

**Files:**

- Create: `site/README.md`
- Modify: `README.md`
- Test: manual verification against the spec's acceptance criteria

**Interfaces:**

- Consumes: the complete site from Tasks 1–10.
- Produces: nothing further; this task gates the release.

- [ ] **Step 1: Run the whole suite and the production build**

Run: `cd site && bun run test && bun run build && bun run preview`
Expected: all suites pass, build succeeds, preview serves `dist/`.

Keep the preview server running for the next four steps. Note the URL it prints — it includes the `/cloud-app/` base path.

- [ ] **Step 2: Verify the page at three widths**

In the browser devtools device toolbar, load the preview at 375px, 768px, and 1440px.

At each width confirm: no horizontal scrollbar on `<body>`; the hero headline wraps without any word overflowing its container; code blocks scroll inside their own panel rather than widening the page; the manifest→stack columns stack below 768px with connectors hidden.

If the hero headline overflows at 375px, reduce the `clamp()` minimum in `src/sections/hero.ts` from `2.25rem` — do not shrink the container.

- [ ] **Step 3: Verify the page without JavaScript**

Disable JavaScript in devtools and reload.

Expected: all eight sections are fully visible and readable; the first code panel is shown; copy buttons are absent; connector lines are absent. Nothing is blank or clipped.

- [ ] **Step 4: Verify reduced motion**

Enable "Reduce motion" at the OS level, reload.

Expected: no travel on any reveal; connectors appear immediately and undrawn; anchor scrolling is instant.

- [ ] **Step 5: Verify keyboard navigation and screen-reader labelling**

Tab from the top of the page.

Expected: the skip link appears first and jumps to `#main`; every link and button shows a visible focus ring against the dark surface; the tab group takes one Tab stop and moves between tabs with arrow keys; activating a copy button announces "Copied" through the live region.

- [ ] **Step 6: Run Lighthouse**

In devtools → Lighthouse, run Performance, Accessibility, Best Practices, and SEO against the preview URL in a fresh incognito window.

Expected: Performance ≥ 95, Accessibility ≥ 95.

If Accessibility is below 95, fix what it reports before continuing — contrast failures mean a token moved and `tests/tokens.test.ts` should have caught it, so re-run the suite too. Stop the preview server when finished.

- [ ] **Step 7: Write `site/README.md`**

````markdown
# cloud-app site

The landing page for cloud-app, built with Vite and bun and published to GitHub
Pages by `.github/workflows/site.yml`.

```bash
bun install
bun run dev     # local dev server
bun run test    # unit tests, schema checks, contrast checks
bun run build   # type-check, prerender, and bundle into dist/
```
````

## How it fits together

Sections are TypeScript modules under `src/sections/` that return HTML strings.
`src/prerender.ts` composes them into `index.html` before Vite builds, so the
published page is static and readable without JavaScript. The modules under
`src/behaviors/` only enhance that markup.

Every YAML sample in `src/content.ts` is validated against
`terraform/schema/cloud-app.schema.json` by `tests/content.test.ts`. If you edit
a sample and the test fails, the sample is wrong — not the test.

`index.html` is generated. Do not commit it or edit it directly; edit
`index.template.html` or the section modules instead.

````

- [ ] **Step 8: Link the site from the root README**

In `README.md`, insert this line directly below the opening paragraph that ends
"...wired together over private networking by default.":

```markdown
Landing page: <https://vgmello.github.io/cloud-app/> (source in [`site/`](site/)).
````

- [ ] **Step 9: Commit**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git add site/README.md README.md
git commit -m "docs(site): document the site build and link it from the root README"
```

- [ ] **Step 10: Open the pull request**

```bash
cd /Users/vgmello-dev/repos/projects/deploy2
git push -u origin HEAD
gh pr create --fill
```

Confirm the `site` workflow's `build` job passes on the pull request and that the
`deploy` job does not run until merge.

---

## Verification Summary

The plan is complete when:

- `cd site && bun run test` passes: token contrast, schema-validated samples, prerender structure, and all behaviour suites.
- `cd site && bun run build` emits `dist/index.html` containing all eight section ids and no `<!--SECTIONS-->` marker.
- The page renders completely with JavaScript disabled.
- Lighthouse Performance and Accessibility are both ≥ 95.
- The `site` workflow builds on pull requests and publishes to Pages on merge to `main`.
