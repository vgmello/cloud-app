import { describe, expect, it } from "vitest";
import { hero } from "../src/sections/hero";
import { DOCS, sample } from "../src/content";

function render(): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = hero.render();
  return host;
}

describe("hero section", () => {
  it("states the headline in the only h1", () => {
    const heading = render().querySelector("h1");
    expect(heading?.textContent).toContain("without writing Terraform");
  });

  it("links both calls to action at the documented URLs", () => {
    const hrefs = [...render().querySelectorAll("a")].map((link) =>
      link.getAttribute("href"),
    );
    expect(hrefs).toContain(DOCS.usage);
    expect(hrefs).toContain(DOCS.repo);
  });

  it("renders a tab group with one panel per sample and only the first visible", () => {
    const host = render();
    const tabs = host.querySelectorAll('[role="tab"]');
    const panels = host.querySelectorAll<HTMLElement>('[role="tabpanel"]');
    expect(tabs).toHaveLength(2);
    expect(panels).toHaveLength(2);
    expect(panels[0]?.hasAttribute("hidden")).toBe(false);
    expect(panels[1]?.hasAttribute("hidden")).toBe(true);
  });

  it("wires each tab to its panel with matching aria ids", () => {
    for (const tab of render().querySelectorAll('[role="tab"]')) {
      const panelId = tab.getAttribute("aria-controls");
      expect(panelId).toBeTruthy();
      expect(
        render().querySelector(`#${panelId}`)?.getAttribute("aria-labelledby"),
      ).toBe(tab.id);
    }
  });

  it("escapes the code sample rather than injecting it as markup", () => {
    const host = render();
    const code =
      host.querySelector("#panel-hero-manifest pre")?.textContent ?? "";
    expect(code).toBe(sample("hero-manifest").code);
  });

  it("hides copy buttons until JavaScript enables them", () => {
    for (const button of render().querySelectorAll("[data-copy-target]")) {
      expect(button.hasAttribute("hidden")).toBe(true);
    }
  });
});
