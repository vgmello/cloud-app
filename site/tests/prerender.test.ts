import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { renderDocument } from "../src/prerender";
import { SECTIONS } from "../src/sections";

const template = readFileSync(resolve(process.cwd(), "index.template.html"), "utf8");

function documentFrom(markup: string): Document {
  return new DOMParser().parseFromString(markup, "text/html");
}

describe("renderDocument", () => {
  it("replaces the marker with section markup", () => {
    const output = renderDocument(template);
    expect(output).not.toContain("<!--SECTIONS-->");
    expect(output.length).toBeGreaterThan(template.length);
  });

  it("throws when the template has no marker", () => {
    expect(() => renderDocument("<html></html>")).toThrow(/marker/);
  });

  it("renders every registered section into main", () => {
    const doc = documentFrom(renderDocument(template));
    for (const section of SECTIONS) {
      const element = doc.getElementById(section.id);
      expect(
        element,
        `section #${section.id} is missing from the document`,
      ).not.toBeNull();
      expect(element?.closest("main")).not.toBeNull();
    }
  });

  it("has exactly one h1", () => {
    expect(
      documentFrom(renderDocument(template)).querySelectorAll("h1"),
    ).toHaveLength(1);
  });

  it("is readable without JavaScript — no section is hidden by a reveal class", () => {
    const doc = documentFrom(renderDocument(template));
    expect(doc.querySelectorAll(".will-reveal")).toHaveLength(0);
  });
});
