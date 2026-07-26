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
          aria-label="Copy ${escapeHtml(filename)}"
          class="rounded-md border border-line px-2.5 py-1 font-mono text-xs text-muted transition-colors duration-150 hover:text-ink"
        >
          Copy
        </button>
      </div>
      <pre
        id="quickstart-${id}"
        tabindex="0"
        role="region"
        aria-label="${escapeHtml(filename)}"
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
