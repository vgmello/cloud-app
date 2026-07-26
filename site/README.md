# cloud-app site

The landing page for cloud-app, built with Vite and bun and published to GitHub
Pages by `.github/workflows/site.yml`.

```bash
bun install
bun run dev     # local dev server
bun run test    # unit tests, schema checks, contrast checks
bun run build   # type-check, prerender, and bundle into dist/
```

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
