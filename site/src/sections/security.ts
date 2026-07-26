import { html, escapeHtml } from "../lib/html";
import { DOCS } from "../content";
import type { Section } from "./index";

interface Property {
  readonly term: string;
  readonly detail: string;
}

const PROPERTIES: readonly Property[] = [
  {
    term: "Private by default",
    detail:
      "private endpoints and private DNS for data services; public ingress is an explicit opt-in per app",
  },
  {
    term: "Resource-group-scoped identities",
    detail:
      "the deploy identity for a stack can only touch that stack's resource group",
  },
  {
    term: "OIDC federation, no stored credentials",
    detail:
      "the workflow exchanges a short-lived token; there is no service principal secret to rotate",
  },
  {
    term: "Plan on pull requests, apply on main",
    detail:
      "every change is reviewable as a Terraform plan before anything is applied",
  },
  {
    term: "Per-stack state isolation",
    detail:
      "each stack gets its own state container, so one repo can never read or write another's state",
  },
];

export const security: Section = {
  id: "security",
  render: () => html`
    <section id="security" class="border-b border-line">
      <div class="mx-auto w-full max-w-5xl px-6 py-20 md:py-28">
        <h2
          class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
        >
          The parts a platform team asks about first.
        </h2>

        <dl data-reveal class="mt-12 divide-y divide-line border-y border-line">
          ${PROPERTIES.map(
            (property) => html`
              <div
                class="grid gap-2 py-5 md:grid-cols-[minmax(0,18rem)_1fr] md:gap-8"
              >
                <dt class="text-base font-semibold text-ink">
                  ${escapeHtml(property.term)}
                </dt>
                <dd class="text-sm leading-relaxed">
                  ${escapeHtml(property.detail)}
                </dd>
              </div>
            `,
          )}
        </dl>

        <p data-reveal class="mt-8 text-sm">
          <a
            href="${DOCS.trust}"
            class="text-accent underline underline-offset-4"
            >Read the trust and identity model</a
          >
        </p>
      </div>
    </section>
  `,
};
