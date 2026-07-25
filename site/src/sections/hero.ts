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
