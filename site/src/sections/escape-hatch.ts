import { html, escapeHtml } from "../lib/html";
import { sample, sampleAriaLabel } from "../content";
import type { Section } from "./index";

const MANIFEST = sample("custom-terraform-manifest");
const MANIFEST_ARIA_LABEL = sampleAriaLabel(MANIFEST);

export const escapeHatch: Section = {
  id: "escape-hatch",
  render: () => html`
    <section
      id="escape-hatch"
      aria-labelledby="escape-hatch-heading"
      class="border-b border-line"
    >
      <div
        class="mx-auto grid w-full max-w-5xl gap-10 px-6 py-20 md:grid-cols-2 md:items-center md:py-28"
      >
        <div data-reveal>
          <h2
            id="escape-hatch-heading"
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
          class="relative overflow-hidden rounded-xl border border-line bg-surface"
        >
          <button
            type="button"
            hidden
            data-copy-target="code-${MANIFEST.id}"
            aria-label="Copy ${escapeHtml(MANIFEST_ARIA_LABEL)}"
            class="absolute right-3 top-3 rounded-md border border-line bg-bg/80 px-2.5 py-1 font-mono text-xs text-muted transition-colors duration-150 hover:text-ink"
          >
            Copy
          </button>
          <pre
            id="code-${MANIFEST.id}"
            tabindex="0"
            role="region"
            aria-label="${escapeHtml(MANIFEST_ARIA_LABEL)}"
            class="overflow-x-auto px-5 py-5 font-mono text-[13px] leading-relaxed text-ink/90"
          ><code>${escapeHtml(MANIFEST.code)}</code></pre>
        </div>
      </div>
    </section>
  `,
};
