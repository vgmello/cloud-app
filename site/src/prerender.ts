import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { SECTIONS } from "./sections";

const MARKER = "<!--SECTIONS-->";

export function renderDocument(template: string): string {
  if (!template.includes(MARKER)) {
    throw new Error(`template is missing the ${MARKER} marker`);
  }
  return template.replace(
    MARKER,
    SECTIONS.map((section) => section.render()).join("\n"),
  );
}

export function prerenderToDisk(): void {
  const templatePath = fileURLToPath(
    new URL("../index.template.html", import.meta.url),
  );
  const outputPath = fileURLToPath(new URL("../index.html", import.meta.url));
  writeFileSync(outputPath, renderDocument(readFileSync(templatePath, "utf8")));
}

if (import.meta.main) {
  prerenderToDisk();
}
