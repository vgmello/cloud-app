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
