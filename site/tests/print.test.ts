// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  fileURLToPath(new URL("../src/styles.css", import.meta.url)),
  "utf8",
);

describe("print styles", () => {
  it("un-hides will-reveal content under an @media print rule", () => {
    const printBlockMatch = css.match(/@media print\s*{([\s\S]*?)}\s*}/);
    expect(
      printBlockMatch,
      "expected an @media print block in src/styles.css",
    ).not.toBeNull();

    const printBlock = printBlockMatch![1]!;
    expect(printBlock).toMatch(/\.will-reveal\s*{[^}]*opacity:\s*1/);
    expect(printBlock).toMatch(/\.will-reveal\s*{[^}]*transform:\s*none/);
  });
});
