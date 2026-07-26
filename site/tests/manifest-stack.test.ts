import { describe, expect, it } from "vitest";
import { manifestStack, validateAnchors } from "../src/sections/manifest-stack";
import { sample } from "../src/content";

function render(): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = manifestStack.render();
  return host;
}

describe("manifest→stack section", () => {
  it("renders the manifest sample verbatim", () => {
    const host = render();
    const lines = [...host.querySelectorAll("[data-manifest-line]")].map(
      (line) => line.textContent,
    );
    expect(lines.join("\n")).toBe(sample("stack-manifest").code.trimEnd());
  });

  it("points every connector source at an element that exists", () => {
    const host = render();
    const sources = [
      ...host.querySelectorAll<HTMLElement>("[data-connect-from]"),
    ];
    // Pinned count: exactly the two truthful anchors (app: -> res-app,
    // database: -> res-db). A change to this number should be a deliberate
    // decision, not a silent side effect of an ANCHORS edit.
    expect(sources.length).toBe(2);
    for (const source of sources) {
      expect(
        host.querySelector(`#${source.dataset.connectFrom}`),
      ).not.toBeNull();
    }
  });

  it("throws naming the offending key when an ANCHORS key drifts from the manifest", () => {
    // Simulates content.ts drifting out from under ANCHORS: a manifest with
    // no "database:" line at all. Without validation this would silently
    // drop the connector instead of failing loudly.
    expect(() => validateAnchors(["app:", "  port: 8080"])).toThrow(
      /database:/,
    );
  });

  it("does not throw when every ANCHORS key matches a manifest line", () => {
    expect(() =>
      validateAnchors(sample("stack-manifest").code.trimEnd().split("\n")),
    ).not.toThrow();
  });

  it("provides an svg canvas for the connector lines", () => {
    expect(
      render().querySelector("[data-connectors] svg[data-connector-canvas]"),
    ).not.toBeNull();
  });

  it("marks the resource list as reveal targets", () => {
    expect(render().querySelectorAll("[data-reveal]").length).toBeGreaterThan(
      0,
    );
  });

  it("describes the diagram for screen readers", () => {
    const host = render();
    const canvas = host.querySelector("[data-connector-canvas]");
    expect(canvas?.getAttribute("aria-hidden")).toBe("true");
    expect(host.querySelector("h2")?.textContent).toBeTruthy();
  });
});
