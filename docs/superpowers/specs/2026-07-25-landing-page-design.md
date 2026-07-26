# cloud-app landing page — design

**Date:** 2026-07-25
**Status:** approved, ready for implementation planning

## Purpose

A single marketing page for the cloud-app open-source project. The audience is
developers and platform engineers who land on the repo or a shared link and need
to understand, in under thirty seconds, that they can ship a full Azure stack by
writing a twelve-line YAML manifest instead of Terraform.

Success: a visitor reaches `docs/usage.md` or the GitHub repo with a correct
mental model of the manifest and the Action step. There is no signup, no
pricing, and no lead capture.

## Scope

In scope: one static page, its build, and a GitHub Pages deployment workflow.

Out of scope: a docs site (the markdown in `docs/` stays canonical), an
interactive manifest playground, analytics, and any change to the engine or
Terraform modules.

## Stack and location

The site lives in a new top-level `site/` directory, isolated from the engine
and Terraform trees so its tooling never touches CI for the platform itself.

- **Build:** Vite, with bun as the package manager and script runner.
- **Language:** vanilla TypeScript. No framework runtime.
- **Styles:** Tailwind CSS v4 through `@tailwindcss/vite`, with the theme
  defined CSS-first in `@theme`.
- **Output:** static assets in `site/dist`, deployed to GitHub Pages.

Vanilla TypeScript is a deliberate constraint. The page has three interactive
behaviours — code tabs, copy buttons, and scroll-driven reveals — none of which
justify a framework, and the resulting bundle is a few kilobytes of JavaScript.

### Module layout

The page is assembled from section partials rather than one large HTML file, so
each section stays independently readable and editable:

- `index.html` — document shell, meta tags, section mount points.
- `src/sections/*.ts` — one module per section, each exporting a function that
  returns that section's markup as a string.
- `src/main.ts` — mounts sections in order, then initialises behaviours.
- `src/behaviors/tabs.ts`, `copy.ts`, `reveal.ts` — one concern each, each
  operating on `data-` attributes so markup and behaviour stay decoupled.
- `src/styles.css` — Tailwind import, `@theme` tokens, the handful of component
  classes that repeat.
- `src/content.ts` — every code sample and every string of body copy, typed.

Content lives apart from markup so copy edits never require touching layout, and
so the code samples can be checked against the real manifest schema.

## Visual direction

Dark, developer-first, code as the hero — the Mastra-leaning direction of the
three mocked up. A near-black canvas with a faint grid, restrained
monospace accents, and a single teal accent colour. Stripe's contribution is
structural rather than chromatic: generous vertical rhythm, confident type
scale, and the discipline of one idea per section.

The colour strategy is **restrained**: tinted neutrals carrying the surface,
with the accent held under ten percent of the page. The accent earns its
appearances — active tab, link underline, the connective lines in the
manifest-to-stack diagram — and appears nowhere decoratively.

### Tokens

Defined in OKLCH in the `@theme` block:

| Role              | Value                    | Use                          |
| ----------------- | ------------------------ | ---------------------------- |
| `--color-bg`      | `oklch(0.145 0.005 260)` | page canvas                  |
| `--color-surface` | `oklch(0.185 0.006 260)` | code panels, bordered blocks |
| `--color-line`    | `oklch(0.26 0.008 260)`  | hairline borders             |
| `--color-ink`     | `oklch(0.96 0.003 260)`  | headings, primary text       |
| `--color-muted`   | `oklch(0.72 0.008 260)`  | body copy, secondary text    |
| `--color-accent`  | `oklch(0.78 0.13 180)`   | teal accent                  |

`--color-muted` on `--color-bg` must be verified at or above 4.5:1 before the
page ships; if it falls short it moves toward the ink end of the ramp rather
than the design keeping a dimmer grey for elegance.

### Typography

One sans family for the interface and one monospace family for code, paired on a
genuine contrast axis. Headings run tight but never below `-0.04em` tracking.
The hero display size caps at 4.5rem. Body copy holds to a 68ch measure.
`text-wrap: balance` on headings, `pretty` on prose.

### Motion

Motion is part of the build, not a pass afterwards. Three uses, each tied to
what it reveals:

1. Section content fades and rises slightly on first view, staggered within a
   section but never applied uniformly to every section.
2. The manifest-to-stack diagram draws its connective lines as it enters view —
   the one moment where motion carries meaning rather than polish.
3. Tab and copy interactions transition state instantly, under 150ms.

All easing is exponential ease-out. No bounce, no elastic. Every animation has a
`prefers-reduced-motion: reduce` alternative that resolves to a crossfade or an
instant state change.

Reveals enhance an already-visible default: sections render fully without
JavaScript, and the reveal class only adds the entrance. A headless renderer or
a background tab must never produce a blank page.

### Constraints carried from the design review

- No eyebrow kickers above section headings. The hero may carry one short
  qualifying line as a deliberate brand element; no other section repeats it.
- Numbers appear only in "How it works", which is a genuine ordered sequence.
- No gradient text, no side-stripe borders, no decorative glassmorphism.
- "What you get" is a typographic spec list, not a grid of identical icon cards.

## Sections

Eight sections, in this order.

**1. Hero.** Headline "Ship Azure infra without writing Terraform", a one-line
subhead naming the manifest and the Action step, two calls to action — "Get
started" and "View on GitHub" — and a tabbed code
panel showing `cloud-app.yml` and `deploy.yml`. The manifest is the
demonstration; no illustration substitutes for it.

**2. Manifest to stack.** The payoff. Twelve lines of YAML on the left, the
resources they provision on the right: Container App with ingress, managed
identity, Key Vault, Postgres with a private endpoint, private DNS. Connective
lines animate on entry to tie each manifest line to what it creates. This is the
most persuasive section on the page and takes the most implementation care.

**3. How it works.** Three steps: write the manifest, add one step to your
workflow, then pull requests plan and main applies. The only numbered sequence.

**4. What you get.** Compute — Container Apps, Functions as container or runtime
code, Static Web Apps. Shared services — Key Vault, Postgres or SQL Server, blob
storage, private endpoints. Presented as a dense spec list.

**5. Environments and overrides.** One manifest, many environments, shown
through the deep merge: a base `database.size: small` with
`environments.prod.database.size: medium` overriding it.

**6. Escape hatch.** `terraform: ./terraform` merges your own `*.tf` into a
custom child module that receives platform context and applies under the same
resource-group-scoped identity. This answers the objection that the platform
cannot model everything.

**7. Private by default.** Private networking unless explicitly opted out,
resource-group-scoped deploy identities, OIDC federation, plan on pull requests
and apply on main, per-stack state isolation. The section that lets a platform
team say yes.

**8. Quickstart and footer.** Both files, copy-pasteable with a copy button,
then links to `docs/usage.md`, `docs/trust-modes.md`, the GitHub repository, and
the MIT license.

Every documentation link on the page — including the hero's "Get started" —
points at the rendered file on GitHub, since the site does not host the docs
itself. The links are defined once in `src/content.ts` against a single
repository-URL constant so they cannot drift apart.

The page does not mention the platform's pre-release status; that remains in the
README, which is where an evaluating engineer will look.

## Content accuracy

Every code sample on the page is copied from, or validated against, the real
manifest schema at `terraform/schema/cloud-app.schema.json`. A sample that would
fail validation is a bug, not a typo. The build includes a check that extracts
the YAML samples from `src/content.ts` and validates them against the schema, so
the page cannot silently drift from the platform it describes.

## Accessibility

Semantic landmarks and a single `h1`. Tabs implement the ARIA tabs pattern with
arrow-key navigation. Copy buttons announce success through a live region rather
than colour alone. Focus rings are visible against the dark surface and never
removed. All text meets the contrast floors above. The page is fully readable
and navigable with JavaScript disabled; only tabs, copy, and reveals degrade.

## Deployment

A GitHub Actions workflow builds and publishes the site:

- Triggers on pushes to `main` that touch `site/**`, and on pull requests
  touching the same paths (build only, no publish).
- Steps: checkout, `oven-sh/setup-bun`, `bun install --frozen-lockfile`,
  `bun run build`, then upload and deploy the Pages artifact.
- Permissions are minimal: `contents: read`, `pages: write`, `id-token: write`.
- Concurrency is grouped on `pages` so a queued deploy supersedes an older one.

Vite's `base` is set to the repository path so relative assets resolve under the
project Pages URL. If a custom domain is configured later, `base` returns to
`/`.

The existing platform CI workflow is left untouched; the site's checks run only
on site paths.

## Testing

- `bun run build` must succeed with no TypeScript errors.
- The schema check described above runs in the same workflow as the build.
- Lighthouse expectations, verified manually before the first deploy:
  performance and accessibility both at or above 95.
- Visual verification at 375px, 768px, and 1440px. Headings must not overflow at
  any of those widths — the hero copy is checked at the smallest.
- Reduced-motion verified by toggling the OS setting and confirming no content
  is hidden.

## Risks

The manifest-to-stack diagram is the section most likely to consume
disproportionate effort. If the animated correspondence proves fragile, the
fallback is a static two-column layout with the connective lines drawn but not
animated; the section still works.

Publishing a polished page for a platform that has never run against a live
Azure subscription risks implying more maturity than exists. This was a
deliberate call: the status stays in the README rather than on the page. The
only mitigation is that both calls to action lead to the repository and the
usage docs, where the status and its prerequisites are stated plainly and
immediately. If the gap starts causing confusion, adding a status line to the
footer is the smallest fix.
