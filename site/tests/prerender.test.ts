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

  it("labels every top-level section by its own heading", () => {
    // Without aria-labelledby, a screen reader announces every landmark as
    // just "region" — a user jumping by landmark can't tell manifest→stack
    // apart from capabilities apart from security. Each <section> must
    // reference the id of the heading inside it.
    const doc = documentFrom(renderDocument(template));
    const sections = [...doc.querySelectorAll("main > section")];
    expect(sections.length).toBe(SECTIONS.length);

    for (const section of sections) {
      const labelledby = section.getAttribute("aria-labelledby");
      expect(
        labelledby,
        `section #${section.id} has no aria-labelledby`,
      ).toBeTruthy();

      const heading = doc.getElementById(labelledby!);
      expect(
        heading,
        `no element with id ${JSON.stringify(labelledby)} for section #${section.id}`,
      ).not.toBeNull();
      expect(section.contains(heading)).toBe(true);
      expect(["H1", "H2"]).toContain(heading!.tagName);
      expect(heading!.textContent?.trim()).not.toBe("");
    }
  });

  it("never reuses an aria-label across code blocks with different content", () => {
    // hero, environments, and escape-hatch each show a manifest sample
    // literally named "cloud-app.yml", but the three manifests differ. A
    // screen-reader user tabbing between their copy buttons and <pre>
    // regions previously heard "Copy cloud-app.yml" / "cloud-app.yml" three
    // times over with no way to tell them apart. A label may repeat only
    // when it is attached to identical code (e.g. quickstart deliberately
    // re-offers the same manifest and workflow files shown in hero).
    const doc = documentFrom(renderDocument(template));
    const byLabel = new Map<string, string>();

    for (const element of doc.querySelectorAll<HTMLElement>("[aria-label]")) {
      const label = element.getAttribute("aria-label")!;
      const codeHost =
        element.tagName === "PRE"
          ? element
          : element.hasAttribute("data-copy-target")
            ? doc.getElementById(element.dataset.copyTarget!)
            : null;
      if (!codeHost) continue;

      const code = codeHost.textContent ?? "";
      const seen = byLabel.get(label);
      if (seen === undefined) {
        byLabel.set(label, code);
      } else {
        expect(
          code,
          `aria-label ${JSON.stringify(label)} is reused for two different code blocks`,
        ).toBe(seen);
      }
    }
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
