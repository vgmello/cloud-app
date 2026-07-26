import { html, escapeHtml } from "../lib/html";
import type { Section } from "./index";

interface Step {
  readonly title: string;
  readonly body: string;
}

const STEPS: readonly Step[] = [
  {
    title: "Write the manifest",
    body: "A cloud-app.yml at the root of your repo names the app, its port, and whatever it needs — a database, storage, a second container.",
  },
  {
    title: "Add one step to your workflow",
    body: "The composite action runs inside your own gated job, under your environment protection rules and your OIDC federation.",
  },
  {
    title: "Pull requests plan, main applies",
    body: "Every pull request runs a Terraform plan and leaves it in the run summary. Merging to main applies it under a resource-group-scoped identity.",
  },
];

export const howItWorks: Section = {
  id: "how-it-works",
  render: () => html`
    <section
      id="how-it-works"
      aria-labelledby="how-it-works-heading"
      class="border-b border-line"
    >
      <div class="mx-auto w-full max-w-5xl px-6 py-20 md:py-28">
        <h2
          id="how-it-works-heading"
          class="text-[clamp(1.75rem,3.4vw,2.75rem)] font-semibold tracking-[-0.03em]"
        >
          Three steps, then it is just your pipeline.
        </h2>

        <ol class="mt-12 grid gap-10 md:grid-cols-3">
          ${STEPS.map(
            (step, index) => html`
              <li data-reveal class="border-t border-line pt-5">
                <span class="font-mono text-sm text-accent">0${index + 1}</span>
                <h3 class="mt-3 text-lg font-semibold">
                  ${escapeHtml(step.title)}
                </h3>
                <p class="mt-2 text-sm leading-relaxed">
                  ${escapeHtml(step.body)}
                </p>
              </li>
            `,
          )}
        </ol>
      </div>
    </section>
  `,
};
