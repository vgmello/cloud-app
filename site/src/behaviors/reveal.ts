const STAGGER_MS = 60;
const MAX_STAGGER_STEPS = 4;

export function initReveal(root: ParentNode = document): void {
  const targets = [...root.querySelectorAll<HTMLElement>("[data-reveal]")];
  if (targets.length === 0) return;

  applyStagger(root);

  const prefersReducedMotion =
    typeof matchMedia === "function" &&
    matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (prefersReducedMotion || typeof IntersectionObserver === "undefined") {
    for (const target of targets) target.classList.add("is-revealed");
    return;
  }

  for (const target of targets) target.classList.add("will-reveal");

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-revealed");
        observer.unobserve(entry.target);
      }
    },
    { rootMargin: "0px 0px -10% 0px", threshold: 0.1 },
  );

  for (const target of targets) observer.observe(target);
}

function applyStagger(root: ParentNode): void {
  for (const section of root.querySelectorAll("section")) {
    section
      .querySelectorAll<HTMLElement>("[data-reveal]")
      .forEach((element, index) => {
        const steps = Math.min(index, MAX_STAGGER_STEPS);
        element.style.setProperty("--reveal-delay", `${steps * STAGGER_MS}ms`);
      });
  }
}
