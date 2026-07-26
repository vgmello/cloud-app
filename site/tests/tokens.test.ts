// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { wcagContrast } from "culori";

const css = readFileSync(
  fileURLToPath(new URL("../src/styles.css", import.meta.url)),
  "utf8",
);

function token(name: string): string {
  const match = css.match(new RegExp(`--color-${name}:\\s*([^;]+);`));
  if (!match?.[1])
    throw new Error(`token --color-${name} not found in src/styles.css`);
  return match[1].trim();
}

describe("theme tokens", () => {
  it("body text clears WCAG AA against the page background", () => {
    expect(wcagContrast(token("muted"), token("bg"))).toBeGreaterThanOrEqual(
      4.5,
    );
  });

  it("headings clear WCAG AA against the page background", () => {
    expect(wcagContrast(token("ink"), token("bg"))).toBeGreaterThanOrEqual(4.5);
  });

  it("the accent clears AA for large text and UI against the page background", () => {
    expect(wcagContrast(token("accent"), token("bg"))).toBeGreaterThanOrEqual(
      3,
    );
  });

  it("surface is distinguishable from the page background", () => {
    expect(wcagContrast(token("surface"), token("bg"))).toBeGreaterThan(1);
  });
});
