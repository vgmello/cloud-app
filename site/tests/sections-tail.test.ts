import { describe, expect, it } from "vitest";
import { escapeHatch } from "../src/sections/escape-hatch";
import { security } from "../src/sections/security";
import { quickstart } from "../src/sections/quickstart";
import { DOCS, sample } from "../src/content";

function render(markup: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = markup;
  return host;
}

describe("escape hatch", () => {
  it("shows the custom terraform manifest sample verbatim", () => {
    expect(render(escapeHatch.render()).querySelector("pre")?.textContent).toBe(
      sample("custom-terraform-manifest").code,
    );
  });

  it("states the guardrail, not just the feature", () => {
    expect(render(escapeHatch.render()).textContent).toMatch(/resource group/i);
  });
});

describe("trust model", () => {
  it("lists the security properties as a description list", () => {
    expect(
      render(security.render()).querySelectorAll("dt").length,
    ).toBeGreaterThanOrEqual(4);
  });

  it("links the trust-modes documentation", () => {
    const hrefs = [...render(security.render()).querySelectorAll("a")].map(
      (a) => a.getAttribute("href"),
    );
    expect(hrefs).toContain(DOCS.trust);
  });
});

describe("quickstart and footer", () => {
  it("renders both files with their own copy buttons", () => {
    const host = render(quickstart.render());
    const buttons = [
      ...host.querySelectorAll<HTMLElement>("[data-copy-target]"),
    ];
    expect(buttons).toHaveLength(2);
    for (const button of buttons) {
      expect(button.hasAttribute("hidden")).toBe(true);
      expect(
        host.querySelector(`#${button.dataset.copyTarget}`),
      ).not.toBeNull();
    }
  });

  it("links usage, trust, repository, and license", () => {
    const hrefs = [...render(quickstart.render()).querySelectorAll("a")].map(
      (a) => a.getAttribute("href"),
    );
    for (const url of [DOCS.usage, DOCS.trust, DOCS.repo, DOCS.license]) {
      expect(hrefs).toContain(url);
    }
  });

  it("contains the page footer", () => {
    expect(render(quickstart.render()).querySelector("footer")).not.toBeNull();
  });
});

describe("all three sections", () => {
  it("uses exactly one h2 each and no h1", () => {
    for (const section of [escapeHatch, security, quickstart]) {
      const host = render(section.render());
      expect(host.querySelectorAll("h1")).toHaveLength(0);
      expect(host.querySelectorAll("h2")).toHaveLength(1);
    }
  });
});
