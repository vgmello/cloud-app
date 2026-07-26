import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { terraform, ALLOWED_PROVIDERS } from "../src/sections/terraform";
import { SECTIONS } from "../src/sections";
import { DOCS } from "../src/content";

function render(): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = terraform.render();
  return host;
}

// Source of truth for the allowlist is engine/cloudapp/customtf.py. Parsed
// (rather than hardcoded here a third time) so a change to the engine's
// ALLOWED_PROVIDERS dict makes this test fail instead of the page silently
// going stale — see also src/sections/terraform.ts's ALLOWED_PROVIDERS.
function enginesAllowedProviders(): string[] {
  const source = readFileSync(
    resolve(process.cwd(), "../engine/cloudapp/customtf.py"),
    "utf8",
  );
  const dictMatch = source.match(/ALLOWED_PROVIDERS\s*=\s*\{([\s\S]*?)\n\}/);
  const dictBody = dictMatch?.[1];
  if (!dictBody) {
    throw new Error("could not find ALLOWED_PROVIDERS dict in customtf.py");
  }
  const keys = [...dictBody.matchAll(/^\s*"([a-z0-9_]+)"\s*:/gm)]
    .map((match) => match[1])
    .filter((key): key is string => key !== undefined);
  if (keys.length === 0) {
    throw new Error("ALLOWED_PROVIDERS dict in customtf.py appears empty");
  }
  return keys;
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

  it("states the full provider allowlist by name, and no other provider names", () => {
    const engineProviders = enginesAllowedProviders();

    // The page's own list must exactly match the engine's — every name
    // present, no extras.
    expect(new Set(ALLOWED_PROVIDERS)).toEqual(new Set(engineProviders));

    const text = render().textContent ?? "";
    for (const provider of engineProviders) {
      expect(text).toContain(provider);
    }
  });

  it("does not claim any Terraform provider works", () => {
    const text = render().textContent ?? "";
    expect(text).not.toMatch(/any (terraform )?provider/i);
  });

  it("does not advertise an S3 state backend", () => {
    const text = render().textContent ?? "";
    expect(text).not.toMatch(/s3/i);
  });

  it("states the roadmap line: Azure today, portable core, modules Azure-only", () => {
    const text = render().textContent ?? "";
    expect(text).toMatch(/azure today/i);
    expect(text).toMatch(/platform modules underneath are azure-only/i);
  });

  it("links the trust-modes documentation", () => {
    const hrefs = [...render().querySelectorAll("a")].map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toContain(DOCS.trust);
  });
});
