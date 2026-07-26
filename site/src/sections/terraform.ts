import { html, escapeHtml } from "../lib/html";
import { DOCS } from "../content";
import type { Section } from "./index";

// Mirrors engine/cloudapp/customtf.py's ALLOWED_PROVIDERS keys. Kept in sync
// by tests/terraform.test.ts, which parses that file and compares this list
// against it, so a drift in either place fails the test.
export const ALLOWED_PROVIDERS = [
  "random",
  "null",
  "tls",
  "time",
  "local",
  "external",
  "azuread",
  "azapi",
] as const;

interface Property {
  readonly lead: string;
  readonly detail: string;
}

const PROPERTIES: readonly Property[] = [
  {
    lead: "Ordinary modules.",
    detail:
      "The engine compiles the manifest to a normalized JSON document and a tfvars.json, then feeds them into checked-in Terraform under terraform/azure/. Nothing is generated behind your back — you can read every module it applies.",
  },
  {
    lead: "Standard state.",
    detail:
      "An azurerm backend you own, holding ordinary Terraform state in a container you control.",
  },
  {
    lead: "Real plans.",
    detail:
      "Every change runs a Terraform plan on the pull request, in the format you already know how to read, there to read in the run summary before anything is applied.",
  },
];

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

        <p class="prose-measure mt-4 text-base leading-relaxed">
          The manifest is data, not a format that owns you. What it produces is
          the thing you would have written by hand.
        </p>

        <ul data-reveal class="mt-10 max-w-3xl space-y-5 border-t border-line pt-6">
          ${PROPERTIES.map(
            (property) => html`
              <li class="text-sm leading-relaxed">
                <span class="font-semibold text-ink"
                  >${escapeHtml(property.lead)}</span
                >
                ${escapeHtml(property.detail)}
              </li>
            `,
          )}
        </ul>

        <p data-reveal class="prose-measure mt-10 text-lg leading-relaxed text-ink">
          No proprietary runtime, no agent, no control plane holding your
          infrastructure hostage. Walk away tomorrow and the Terraform and the
          state are still yours to run directly.
        </p>

        <p data-reveal class="prose-measure mt-6 text-sm leading-relaxed">
          Your own <span class="font-mono text-ink">*.tf</span> files run under
          the same rules. Providers in that module come from a fixed
          allowlist — today
          ${ALLOWED_PROVIDERS.map(
            (name, index) => html`<span class="font-mono text-ink"
                >${escapeHtml(name)}</span
              >${index === ALLOWED_PROVIDERS.length - 1 ? "" : ", "}`,
          )}
          — because letting caller code declare arbitrary providers or backends
          would route around the identity the whole platform authenticates
          through. Every provider on that list is either credential-less or
          authenticates as that same identity.
        </p>

        <p data-reveal class="prose-measure mt-6 text-sm text-muted">
          Azure today. The manifest's core shape is portable; a few fields —
          ingress options, function runtimes — still mirror Azure directly.
          The platform modules underneath are Azure-only. Other clouds are
          next.
        </p>

        <p data-reveal class="mt-8 text-sm">
          <a href="${DOCS.trust}" class="text-accent underline underline-offset-4"
            >Read the trust and identity model</a
          >
        </p>
      </div>
    </section>
  `,
};
