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
    id: "res-db",
    title: "Postgres flexible server",
    detail: "private endpoint, private DNS, generated credentials",
  },
  {
    id: "res-identity",
    title: "Managed identity",
    detail: "per-app, scoped to Key Vault and the shared registry, not federated",
  },
  {
    id: "res-vault",
    title: "Key Vault",
    detail: "secrets synced from the workflow, referenced by the app",
  },
];

/**
 * Manifest lines that anchor a connector, keyed by the resource they create.
 * Anchor only what is true: `app:` really provisions the Container App, and
 * `database:` really provisions Postgres. Managed identity and Key Vault are
 * deliberately left unanchored — they're what the platform adds without
 * being asked, which is the section's point.
 */
const ANCHORS: Record<string, string> = {
  "app:": "res-app",
  "database:": "res-db",
};

/**
 * Guards against ANCHORS drifting from the manifest text in `content.ts`.
 * Both files can change independently, and a key that stops matching any
 * manifest line would otherwise drop its connector silently. Fail loudly
 * instead, naming the offending key.
 */
export function validateAnchors(lines: readonly string[]): void {
  for (const key of Object.keys(ANCHORS)) {
    if (!lines.includes(key)) {
      throw new Error(
        `manifest-stack: ANCHORS key ${JSON.stringify(key)} does not match any line of the "stack-manifest" sample`,
      );
    }
  }
}

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
    validateAnchors(lines);
    return html`
      <section
        id="manifest-stack"
        aria-labelledby="manifest-stack-heading"
        class="border-b border-line"
      >
        <div class="mx-auto w-full max-w-5xl px-6 py-20 md:py-28">
          <h2
            id="manifest-stack-heading"
            class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
          >
            Six lines in. A whole stack out.
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
