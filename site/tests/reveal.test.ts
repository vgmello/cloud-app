import { afterEach, describe, expect, it, vi } from "vitest";
import { initReveal } from "../src/behaviors/reveal";

type ObserverCallback = (
  entries: Array<{ target: Element; isIntersecting: boolean }>,
) => void;

function stubObserver(): { trigger: ObserverCallback; unobserved: Element[] } {
  const unobserved: Element[] = [];
  let callback: ObserverCallback = () => {};
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(handler: ObserverCallback) {
        callback = handler;
      }
      observe(): void {}
      unobserve(element: Element): void {
        unobserved.push(element);
      }
      disconnect(): void {}
    },
  );
  return { trigger: (entries) => callback(entries), unobserved };
}

function stubMatchMedia(reduced: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({ matches: reduced, addEventListener: vi.fn() }),
  );
}

function setup(): HTMLElement[] {
  document.body.innerHTML = `
    <section id="one">
      <div data-reveal>a</div>
      <div data-reveal>b</div>
    </section>
    <section id="two">
      <div data-reveal>c</div>
    </section>
  `;
  return [...document.querySelectorAll<HTMLElement>("[data-reveal]")];
}

describe("initReveal", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("adds the hidden state only from JavaScript, then reveals on intersection", () => {
    stubMatchMedia(false);
    const observer = stubObserver();
    const targets = setup();
    initReveal(document);

    expect(
      targets.every((element) => element.classList.contains("will-reveal")),
    ).toBe(true);
    observer.trigger([{ target: targets[0]!, isIntersecting: true }]);
    expect(targets[0]?.classList.contains("is-revealed")).toBe(true);
    expect(targets[1]?.classList.contains("is-revealed")).toBe(false);
  });

  it("stops observing an element once it has been revealed", () => {
    stubMatchMedia(false);
    const observer = stubObserver();
    const targets = setup();
    initReveal(document);
    observer.trigger([{ target: targets[0]!, isIntersecting: true }]);
    expect(observer.unobserved).toEqual([targets[0]]);
  });

  it("ignores entries that are not intersecting", () => {
    stubMatchMedia(false);
    const observer = stubObserver();
    const targets = setup();
    initReveal(document);
    observer.trigger([{ target: targets[0]!, isIntersecting: false }]);
    expect(targets[0]?.classList.contains("is-revealed")).toBe(false);
  });

  it("staggers delays within a section and restarts them in the next", () => {
    stubMatchMedia(false);
    stubObserver();
    const targets = setup();
    initReveal(document);
    expect(targets[0]?.style.getPropertyValue("--reveal-delay")).toBe("0ms");
    expect(targets[1]?.style.getPropertyValue("--reveal-delay")).toBe("60ms");
    expect(targets[2]?.style.getPropertyValue("--reveal-delay")).toBe("0ms");
  });

  it("reveals everything immediately when reduced motion is requested", () => {
    stubMatchMedia(true);
    stubObserver();
    const targets = setup();
    initReveal(document);
    expect(
      targets.every((element) => element.classList.contains("is-revealed")),
    ).toBe(true);
    expect(
      targets.some((element) => element.classList.contains("will-reveal")),
    ).toBe(false);
  });

  it("reveals everything when IntersectionObserver is unavailable", () => {
    stubMatchMedia(false);
    vi.stubGlobal("IntersectionObserver", undefined);
    const targets = setup();
    initReveal(document);
    expect(
      targets.every((element) => element.classList.contains("is-revealed")),
    ).toBe(true);
  });
});
