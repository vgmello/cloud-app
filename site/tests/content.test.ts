// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { DOCS, REPO_URL, SAMPLES, sample } from "../src/content";

const schema = JSON.parse(
  readFileSync(
    fileURLToPath(
      new URL("../../terraform/schema/cloud-app.schema.json", import.meta.url),
    ),
    "utf8",
  ),
);

const validate = new Ajv2020({ strict: false, allErrors: true }).compile(
  schema,
);
const manifests = SAMPLES.filter((entry) => entry.kind === "manifest");

describe("code samples", () => {
  it("ships at least one manifest and one workflow sample", () => {
    expect(manifests.length).toBeGreaterThan(0);
    expect(SAMPLES.some((entry) => entry.kind === "workflow")).toBe(true);
  });

  it("gives every sample a unique id", () => {
    expect(new Set(SAMPLES.map((entry) => entry.id)).size).toBe(SAMPLES.length);
  });

  it.each(manifests)("$id validates against the platform schema", (entry) => {
    validate(parse(entry.code));
    expect(validate.errors ?? []).toEqual([]);
  });

  it("parses every workflow sample as YAML", () => {
    for (const entry of SAMPLES.filter((item) => item.kind === "workflow")) {
      expect(parse(entry.code)).toBeTypeOf("object");
    }
  });

  it("throws a useful error for an unknown sample id", () => {
    expect(() => sample("does-not-exist")).toThrow(/does-not-exist/);
  });
});

describe("documentation links", () => {
  it("derives every link from the repository constant", () => {
    for (const url of Object.values(DOCS)) {
      expect(url.startsWith(REPO_URL)).toBe(true);
    }
  });
});
