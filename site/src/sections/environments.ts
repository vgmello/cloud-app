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
            aria-label="Copy ${escapeHtml(MANIFEST.filename)}"
            class="absolute right-3 top-3 rounded-md border border-line bg-bg/80 px-2.5 py-1 font-mono text-xs text-muted transition-colors duration-150 hover:text-ink"
          >
            Copy
          </button>
          <pre
            id="code-${MANIFEST.id}"
            tabindex="0"
            role="region"
            aria-label="${escapeHtml(MANIFEST.filename)}"
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
