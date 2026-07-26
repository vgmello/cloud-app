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
    expect(tabs).toHaveLength(3);
    expect(panels).toHaveLength(3);
    expect(panels[0]?.hasAttribute("hidden")).toBe(false);
    expect(panels[1]?.hasAttribute("hidden")).toBe(true);
    expect(panels[2]?.hasAttribute("hidden")).toBe(true);
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

  describe("the resources tab", () => {
    it("renders as a third tab wired to its panel like the other two", () => {
      const host = render();
      const resourcesTab = host.querySelector(`#tab-${sample("hero-resources").id}`);
      expect(resourcesTab).not.toBeNull();
      expect(resourcesTab?.getAttribute("role")).toBe("tab");

      const panelId = resourcesTab?.getAttribute("aria-controls");
      const panel = host.querySelector(`#${panelId}`);
      expect(panel).not.toBeNull();
      expect(panel?.getAttribute("role")).toBe("tabpanel");
      expect(panel?.getAttribute("aria-labelledby")).toBe(resourcesTab?.id);
    });

    it("shows the resources sample verbatim", () => {
      const host = render();
      const code = host.querySelector(
        `#panel-${sample("hero-resources").id} pre`,
      )?.textContent;
      expect(code).toBe(sample("hero-resources").code);
    });

    it("keeps the pre keyboard-accessible with no copy button, since there is nothing to paste", () => {
      const host = render();
      const panel = host.querySelector(`#panel-${sample("hero-resources").id}`);
      const pre = panel?.querySelector("pre");
      expect(pre?.getAttribute("role")).toBe("region");
      expect(pre?.getAttribute("tabindex")).toBe("0");
      expect(pre?.getAttribute("aria-label")).toBeTruthy();
      expect(panel?.querySelector("[data-copy-target]")).toBeNull();
    });
  });
});
