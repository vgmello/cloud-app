import { describe, expect, it } from "vitest";
import { manifestStack } from "../src/sections/manifest-stack";
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
    expect(sources.length).toBeGreaterThan(0);
    for (const source of sources) {
      expect(
        host.querySelector(`#${source.dataset.connectFrom}`),
      ).not.toBeNull();
    }
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
