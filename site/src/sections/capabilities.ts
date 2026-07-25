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
