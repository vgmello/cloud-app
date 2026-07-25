import { afterEach, describe, expect, it, vi } from "vitest";
import { initConnectors } from "../src/behaviors/connect";

function rect(top: number, left = 0, width = 100, height = 20): DOMRect {
  return {
    top,
    left,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON: () => ({}),
  } as DOMRect;
}

function transitionEnd(propertyName: string): Event {
  const event = new Event("transitionend", { bubbles: true });
  Object.defineProperty(event, "propertyName", { value: propertyName });
  return event;
}

function nextAnimationFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

function setup(): void {
  document.body.innerHTML = `
    <div data-connectors>
      <svg data-connector-canvas aria-hidden="true"></svg>
      <span data-connect-from="res-app">app:</span>
      <span data-connect-from="res-db">database:</span>
      <div id="res-app">Container App</div>
      <div id="res-db">Postgres</div>
    </div>
  `;
  const container = document.querySelector<HTMLElement>("[data-connectors]")!;
  container.getBoundingClientRect = () => rect(0, 0, 400, 200);
  document
    .querySelectorAll<HTMLElement>('[data-connect-from], [id^="res-"]')
    .forEach((element, index) => {
      element.getBoundingClientRect = () => rect(index * 40);
    });
}

describe("initConnectors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("draws one line per source anchor", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    expect(
      document.querySelectorAll("[data-connector-canvas] line"),
    ).toHaveLength(2);
  });

  it("gives each line finite coordinates derived from element positions", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    for (const line of document.querySelectorAll(
      "[data-connector-canvas] line",
    )) {
      for (const attribute of ["x1", "y1", "x2", "y2"]) {
        expect(Number.isFinite(Number(line.getAttribute(attribute)))).toBe(
          true,
        );
      }
    }
  });

  it("redraws on resize instead of appending duplicates", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    window.dispatchEvent(new Event("resize"));
    expect(
      document.querySelectorAll("[data-connector-canvas] line"),
    ).toHaveLength(2);
  });

  it("redraws when a reveal transition finishes on the connector container", async () => {
    // The reveal animation settles a manifest line or resource card into
    // its resting position via a CSS transition on that descendant; the
    // transitionend event bubbles up to the [data-connectors] container.
    // jsdom never runs layout or transitions, so this only proves the
    // listener is wired to re-run draw() without duplicating lines — not
    // that coordinates change, which requires a real browser.
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    const container = document.querySelector<HTMLElement>("[data-connectors]")!;
    container.dispatchEvent(transitionEnd("transform"));
    await nextAnimationFrame();
    expect(
      document.querySelectorAll("[data-connector-canvas] line"),
    ).toHaveLength(2);
  });

  it("ignores transitionend events for properties other than transform", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    const canvas = document.querySelector<SVGSVGElement>(
      "[data-connector-canvas]",
    )!;
    const replaceChildren = vi.spyOn(canvas, "replaceChildren");
    replaceChildren.mockClear(); // drop the call made by the initial draw()

    const container = document.querySelector<HTMLElement>("[data-connectors]")!;
    container.dispatchEvent(transitionEnd("opacity"));
    await nextAnimationFrame();

    expect(replaceChildren).not.toHaveBeenCalled();
  });

  it("coalesces a burst of transitionend events into a single redraw", async () => {
    // Scrolling the section into view fires opacity + transform
    // transitionend for every one of the 5 reveal targets — 10 events from
    // one scroll. Redrawing on each would call draw() (replaceChildren() +
    // re-adding connector-draw) 10 times, restarting the 900ms line-draw
    // animation from zero on every call and making the lines stutter.
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    const canvas = document.querySelector<SVGSVGElement>(
      "[data-connector-canvas]",
    )!;
    const replaceChildren = vi.spyOn(canvas, "replaceChildren");
    replaceChildren.mockClear(); // drop the call made by the initial draw()

    const container = document.querySelector<HTMLElement>("[data-connectors]")!;
    const burst = [
      "opacity",
      "transform",
      "opacity",
      "transform",
      "opacity",
      "transform",
      "opacity",
      "transform",
      "opacity",
      "transform",
    ];
    for (const propertyName of burst) {
      container.dispatchEvent(transitionEnd(propertyName));
    }

    // No synchronous redraw from the burst — it must be coalesced.
    expect(replaceChildren).not.toHaveBeenCalled();

    await nextAnimationFrame();

    expect(replaceChildren).toHaveBeenCalledTimes(1);
    expect(
      document.querySelectorAll("[data-connector-canvas] line"),
    ).toHaveLength(2);
  });

  it("skips the drawing animation under reduced motion but still draws lines", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn() }),
    );
    setup();
    initConnectors(document);
    const lines = document.querySelectorAll("[data-connector-canvas] line");
    expect(lines).toHaveLength(2);
    expect(lines[0]?.classList.contains("connector-draw")).toBe(false);
  });

  it("does nothing when the section is absent", () => {
    document.body.innerHTML = "<main></main>";
    expect(() => initConnectors(document)).not.toThrow();
  });
});
