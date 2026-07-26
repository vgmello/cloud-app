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

  it("gives every element a unique id", () => {
    // copy.ts resolves a button's target with `querySelector('#' + id)`,
    // which silently matches whichever element with that id comes first in
    // document order. quickstart.ts deliberately prefixes its ids
    // (`quickstart-<sample id>`) to avoid colliding with hero's copies of
    // the same two samples; nothing else pins that invariant. Without this
    // check, normalising away that prefix would make quickstart's copy
    // buttons silently copy hero's code blocks instead of their own, with
    // every other test still green.
    const doc = documentFrom(renderDocument(template));
    const ids = [...doc.querySelectorAll("[id]")].map((element) => element.id);
    const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
    expect(duplicates).toEqual([]);
  });
});
