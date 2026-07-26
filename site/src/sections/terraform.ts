import { html, escapeHtml } from "../lib/html";
import { DOCS } from "../content";
import type { Section } from "./index";

const ALLOWED_PROVIDERS = [
  "random",
  "null",
  "tls",
  "time",
  "local",
  "external",
  "azuread",
  "azapi",
] as const;

export const terraform: Section = {
  id: "terraform",
  render: () => html`
    <section id="terraform" class="border-b border-line">
      <div class="mx-auto w-full max-w-5xl px-6 py-20 md:py-28">
        <h2
          class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
        >
          It is plain Terraform underneath.
        </h2>

        <div data-reveal class="prose-measure mt-6 space-y-5 text-base leading-relaxed">
          <p>
            The manifest is not a proprietary format you are locked into — it
            is data. The engine turns
            <span class="font-mono text-ink">cloud-app.yml</span> into a
            normalized JSON manifest and a
            <span class="font-mono text-ink">tfvars.json</span>, and feeds
            them into ordinary, checked-in Terraform modules under
            <span class="font-mono text-ink">terraform/azure/</span>. You can
            read every one of them.
          </p>
          <p>
            State is standard Terraform state, in your own backend —
            <span class="font-mono text-ink">azurerm</span> or
            <span class="font-mono text-ink">s3</span>. The S3 option stores
            state only; the resources it describes are still Azure. Every
            change is a real Terraform plan, posted and reviewed on the pull
            request before anything applies.
          </p>
          <p>
            There is no proprietary runtime, no agent, and no control plane
            holding your infrastructure hostage. If you stop using this
            tomorrow, the Terraform and the state are still yours to run
            directly.
          </p>
          <p>
            The escape hatch works the same way: point
            <span class="font-mono text-ink">terraform:</span> at your own
            <span class="font-mono text-ink">*.tf</span> files and they merge
            into a child module with platform context already wired in.
            Providers in that module come from a fixed allowlist — today
            ${ALLOWED_PROVIDERS.map(
              (name, index) => html`<span class="font-mono text-ink"
                >${escapeHtml(name)}</span
              >${index === ALLOWED_PROVIDERS.length - 1 ? "" : ", "}`,
            )}
            — a fixed set, not an open door. Letting caller code declare
            arbitrary providers, backends, or provider blocks would open a way
            around the ambient identity the whole platform authenticates
            through; every provider on the list is either credential-less or
            authenticates through that same ambient identity. You get the
            guardrails without giving up Terraform.
          </p>
          <p class="text-sm text-muted">
            Azure today. The manifest is provider-neutral by design; the
            platform modules underneath are not yet — other clouds are next.
          </p>
          <p class="text-sm">
            <a
              href="${DOCS.trust}"
              class="text-accent underline underline-offset-4"
              >Read the trust and identity model</a
            >
          </p>
        </div>
      </div>
    </section>
  `,
};
