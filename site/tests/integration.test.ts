import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderDocument } from "../src/prerender";

// Deliberately resolved from cwd, not `new URL(..., import.meta.url)` — the
// latter breaks under the jsdom test environment.
const template = readFileSync(
  resolve(process.cwd(), "index.template.html"),
  "utf8",
);

class StubIntersectionObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

/**
 * Mounts the real prerendered document into the jsdom `document` — the same
 * markup `main.ts` boots against in production, not a synthetic fixture.
 */
function mount(): void {
  const doc = new DOMParser().parseFromString(
    renderDocument(template),
    "text/html",
  );
  document.body.innerHTML = doc.body.innerHTML;
}

/**
 * True while `element` (or a `[data-reveal]` ancestor of it) is sitting in
 * the pre-reveal `will-reveal` state — offset by the 12px translateY that
 * `.will-reveal` applies in src/styles.css, and not yet corrected by
 * `.is-revealed`. Used below to fake layout geometry that actually reacts to
 * reveal state, the way a real browser's `getBoundingClientRect` would.
 */
function isPreReveal(element: Element): boolean {
  const host = element.closest<HTMLElement>("[data-reveal]");
  if (!host) return false;
  return (
    host.classList.contains("will-reveal") &&
    !host.classList.contains("is-revealed")
  );
}

/**
 * Stubs getBoundingClientRect on the manifest-stack connector's sources,
 * targets, and container so that measurements move by 12px the instant a
 * `[data-reveal]` ancestor picks up `will-reveal` — mirroring the real CSS.
 * jsdom never runs layout, so without this every rect is a static (0,0,0,0)
 * and connect.ts's draw() would look "correct" no matter when it runs.
 */
function stubConnectorGeometry(): void {
  const baseline = new Map<Element, number>();
  let next = 0;

  const rectFor = (element: Element): DOMRect => {
    if (!baseline.has(element)) {
      baseline.set(element, next);
      next += 40;
    }
    const top = baseline.get(element)! + (isPreReveal(element) ? 12 : 0);
    return {
      top,
      left: 0,
      width: 120,
      height: 20,
      right: 120,
      bottom: top + 20,
      x: 0,
      y: top,
      toJSON: () => ({}),
    } as DOMRect;
  };

  const container = document.querySelector<HTMLElement>(
    "#manifest-stack [data-connectors]",
  )!;
  container.getBoundingClientRect = () => rectFor(container);
  for (const element of container.querySelectorAll<HTMLElement>(
    "[data-connect-from], [id^='res-']",
  )) {
    element.getBoundingClientRect = () => rectFor(element);
  }
}

describe("wiring the real page (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
    document.body.innerHTML = "";
  });

  it("boots every behaviour against the prerendered document via main.ts", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }),
    );
    vi.stubGlobal("IntersectionObserver", StubIntersectionObserver);
    mount();
    stubConnectorGeometry();

    // Exercises the real wiring, in main.ts's own order — not a copy of it —
    // so reordering the calls inside main.ts fails this test.
    await import("../src/main");

    // Copy buttons are unhidden once JavaScript has wired them.
    const copyButtons = [
      ...document.querySelectorAll<HTMLButtonElement>("[data-copy-target]"),
    ];
    expect(copyButtons.length).toBeGreaterThan(0);
    for (const button of copyButtons) {
      expect(button.hidden).toBe(false);
    }

    // Exactly one tabpanel is visible.
    const panels = document.querySelectorAll<HTMLElement>('[role="tabpanel"]');
    expect(panels.length).toBeGreaterThan(0);
    expect([...panels].filter((panel) => !panel.hidden)).toHaveLength(1);

    // Reveal targets are armed for their entrance animation, not yet
    // revealed — nothing has intersected.
    const revealTargets = document.querySelectorAll("[data-reveal]");
    expect(revealTargets.length).toBeGreaterThan(0);
    for (const target of revealTargets) {
      expect(target.classList.contains("will-reveal")).toBe(true);
      expect(target.classList.contains("is-revealed")).toBe(false);
    }

    // Connectors are drawn, and drawn *after* reveal armed its targets: the
    // manifest-stack anchors sit under a [data-reveal] host that is already
    // will-reveal by the time draw() runs, so the geometry connect.ts baked
    // into each <line> already reflects the 12px pre-reveal offset that is
    // present right now. If initConnectors had run before initReveal, the
    // lines would still be sitting at the pre-will-reveal (unoffset)
    // coordinates while the elements themselves had since shifted 12px, and
    // this comparison would fail.
    const container = document.querySelector<HTMLElement>(
      "#manifest-stack [data-connectors]",
    )!;
    const canvas = container.querySelector<SVGSVGElement>(
      "[data-connector-canvas]",
    )!;
    const lines = [...canvas.querySelectorAll("line")];
    expect(lines).toHaveLength(2);

    const frame = container.getBoundingClientRect();
    const sources = [
      ...container.querySelectorAll<HTMLElement>("[data-connect-from]"),
    ];
    expect(sources).toHaveLength(lines.length);

    lines.forEach((line, index) => {
      const source = sources[index]!;
      const target = container.querySelector<HTMLElement>(
        `#${source.dataset.connectFrom}`,
      )!;
      const from = source.getBoundingClientRect();
      const to = target.getBoundingClientRect();
      expect(Number(line.getAttribute("x1"))).toBe(from.right - frame.left);
      expect(Number(line.getAttribute("y1"))).toBe(
        from.top + from.height / 2 - frame.top,
      );
      expect(Number(line.getAttribute("x2"))).toBe(to.left - frame.left);
      expect(Number(line.getAttribute("y2"))).toBe(
        to.top + to.height / 2 - frame.top,
      );
    });
  });
});
