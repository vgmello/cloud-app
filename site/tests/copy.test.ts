import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initCopy } from "../src/behaviors/copy";

function setup(): { button: HTMLButtonElement; status: HTMLElement } {
  document.body.innerHTML = `
    <button type="button" hidden data-copy-target="code-a">Copy</button>
    <pre id="code-a">name: orders-api</pre>
    <div role="status" aria-live="polite" data-copy-status></div>
  `;
  return {
    button: document.querySelector("[data-copy-target]")!,
    status: document.querySelector("[data-copy-status]")!,
  };
}

describe("initCopy", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("reveals copy buttons that are hidden for non-JavaScript readers", () => {
    const { button } = setup();
    initCopy(document, { writeText: vi.fn().mockResolvedValue(undefined) });
    expect(button.hidden).toBe(false);
  });

  it("writes the target element text to the clipboard", async () => {
    const { button } = setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    initCopy(document, { writeText });
    button.click();
    await vi.waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("name: orders-api"),
    );
  });

  it("announces success in the live region and restores the label", async () => {
    const { button, status } = setup();
    initCopy(document, { writeText: vi.fn().mockResolvedValue(undefined) });
    button.click();
    await vi.waitFor(() => expect(status.textContent).toBe("Copied"));
    expect(button.textContent?.trim()).toBe("Copied");
    vi.advanceTimersByTime(2000);
    expect(button.textContent?.trim()).toBe("Copy");
    expect(status.textContent).toBe("");
  });

  it("announces a recoverable message when the clipboard rejects", async () => {
    const { button, status } = setup();
    initCopy(document, {
      writeText: vi.fn().mockRejectedValue(new Error("denied")),
    });
    button.click();
    await vi.waitFor(() =>
      expect(status.textContent).toMatch(/copy manually/i),
    );
  });

  it("ignores buttons whose target is missing", () => {
    document.body.innerHTML =
      '<button data-copy-target="nope" hidden>Copy</button>';
    const writeText = vi.fn();
    initCopy(document, { writeText });
    document.querySelector<HTMLButtonElement>("[data-copy-target]")?.click();
    expect(writeText).not.toHaveBeenCalled();
  });
});
