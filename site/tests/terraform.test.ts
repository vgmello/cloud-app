import { describe, expect, it } from "vitest";
import { terraform } from "../src/sections/terraform";
import { SECTIONS } from "../src/sections";
import { DOCS } from "../src/content";

function render(): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = terraform.render();
  return host;
}

describe("terraform section", () => {
  it("sits between the escape hatch and the trust model", () => {
    const ids = SECTIONS.map((section) => section.id);
    const escapeHatchIndex = ids.indexOf("escape-hatch");
    const securityIndex = ids.indexOf("security");
    const terraformIndex = ids.indexOf("terraform");
    expect(terraformIndex).toBe(escapeHatchIndex + 1);
    expect(securityIndex).toBe(terraformIndex + 1);
  });

  it("uses exactly one h2 and no h1, and does not number itself", () => {
    const host = render();
    expect(host.querySelectorAll("h1")).toHaveLength(0);
    expect(host.querySelectorAll("h2")).toHaveLength(1);
    expect(host.querySelectorAll("ol")).toHaveLength(0);
  });

  it("marks its content as a reveal target", () => {
    expect(render().querySelectorAll("[data-reveal]").length).toBeGreaterThan(
      0,
    );
  });

  it("states the full provider allowlist by name", () => {
    const text = render().textContent ?? "";
    for (const provider of [
      "random",
      "null",
      "tls",
      "time",
      "local",
      "external",
      "azuread",
      "azapi",
    ]) {
      expect(text).toContain(provider);
    }
  });

  it("does not claim any Terraform provider works", () => {
    const text = render().textContent ?? "";
    expect(text).not.toMatch(/any (terraform )?provider/i);
  });

  it("states that state storage in S3 does not mean AWS deployment", () => {
    const text = render().textContent ?? "";
    expect(text).toMatch(/s3/i);
    expect(text).toMatch(/still azure|resources.*azure|azure.*resources/i);
  });

  it("states the roadmap line: provider-neutral manifest, Azure-only modules today", () => {
    const text = render().textContent ?? "";
    expect(text).toMatch(/azure today/i);
    expect(text).toMatch(/provider-neutral/i);
  });

  it("links the trust-modes documentation", () => {
    const hrefs = [...render().querySelectorAll("a")].map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toContain(DOCS.trust);
  });
});
