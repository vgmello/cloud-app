import { describe, expect, it } from "vitest";
import { howItWorks } from "../src/sections/how-it-works";
import { capabilities } from "../src/sections/capabilities";
import { environments } from "../src/sections/environments";
import { SECTIONS } from "../src/sections";
import { sample } from "../src/content";

function render(markup: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = markup;
  return host;
}

describe("how it works", () => {
  it("presents exactly three ordered steps", () => {
    const host = render(howItWorks.render());
    expect(host.querySelectorAll("ol > li")).toHaveLength(3);
  });

  it("is the only section allowed to number itself", () => {
    for (const section of SECTIONS) {
      const hasOrderedList =
        render(section.render()).querySelector("ol") !== null;
      expect(hasOrderedList).toBe(section.id === "how-it-works");
    }
  });

  it("names the plan-on-PR, apply-on-main split", () => {
    expect(render(howItWorks.render()).textContent).toMatch(/pull request/i);
  });
});

describe("capabilities", () => {
  it("lists compute and shared services as description groups, not cards", () => {
    const host = render(capabilities.render());
    expect(host.querySelectorAll("dl").length).toBeGreaterThan(0);
    expect(host.querySelectorAll("dt").length).toBeGreaterThanOrEqual(6);
  });

  it("names every compute type the platform supports", () => {
    const text = render(capabilities.render()).textContent ?? "";
    for (const compute of ["Container Apps", "Functions", "Static Web Apps"]) {
      expect(text).toContain(compute);
    }
  });
});

describe("environments", () => {
  it("shows the environments manifest sample verbatim", () => {
    const host = render(environments.render());
    expect(host.querySelector("pre")?.textContent).toBe(
      sample("environments-manifest").code,
    );
  });

  it("offers a copy button pointing at that sample", () => {
    const host = render(environments.render());
    const button = host.querySelector<HTMLElement>("[data-copy-target]");
    expect(button?.hasAttribute("hidden")).toBe(true);
    expect(host.querySelector(`#${button?.dataset.copyTarget}`)).not.toBeNull();
  });
});

describe("all three sections", () => {
  const sections = [howItWorks, capabilities, environments];

  it("uses h2 for its own heading and never h1", () => {
    for (const section of sections) {
      const host = render(section.render());
      expect(host.querySelectorAll("h1")).toHaveLength(0);
      expect(host.querySelectorAll("h2")).toHaveLength(1);
    }
  });

  it("marks content as reveal targets", () => {
    for (const section of sections) {
      expect(
        render(section.render()).querySelectorAll("[data-reveal]").length,
      ).toBeGreaterThan(0);
    }
  });
});
