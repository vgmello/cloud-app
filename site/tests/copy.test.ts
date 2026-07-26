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

  it("resolves a target whose id contains characters invalid in a bare CSS id selector", async () => {
    // `id`s are generated slugs today, but resolution must not depend on
    // that — interpolating an id straight into `#${id}` breaks (or, worse,
    // silently misresolves) as soon as the id contains a character that CSS
    // selectors treat specially, like a colon.
    document.body.innerHTML = `
      <button type="button" hidden data-copy-target="code:a">Copy</button>
      <pre id="code:a">name: orders-api</pre>
    `;
    const writeText = vi.fn().mockResolvedValue(undefined);
    initCopy(document, { writeText });
    document.querySelector<HTMLButtonElement>("[data-copy-target]")!.click();
    await vi.waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("name: orders-api"),
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

  it("does not issue a second clipboard write while the first one is still in flight", async () => {
    const { button } = setup();
    let resolveWrite: (() => void) | undefined;
    const writeText = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveWrite = resolve;
        }),
    );
    initCopy(document, { writeText });

    button.click();
    button.click(); // rapid re-click before the first write has settled

    expect(writeText).toHaveBeenCalledTimes(1);

    resolveWrite?.();
    await vi.waitFor(() => expect(button.textContent?.trim()).toBe("Copied"));

    // Once the first write has settled, a fresh click is a new copy and
    // should go through normally.
    button.click();
    expect(writeText).toHaveBeenCalledTimes(2);
  });

  it("extends the reset timeout when clicked twice in quick succession", async () => {
    const { button, status } = setup();
    initCopy(document, { writeText: vi.fn().mockResolvedValue(undefined) });
    button.click();
    await vi.waitFor(() => expect(status.textContent).toBe("Copied"));
    expect(button.textContent?.trim()).toBe("Copied");

    // Advance time partway (less than 2000ms)
    vi.advanceTimersByTime(1000);
    expect(button.textContent?.trim()).toBe("Copied");
    expect(status.textContent).toBe("Copied");

    // Click again before the first timer fires
    button.click();
    await vi.waitFor(() => expect(status.textContent).toBe("Copied"));

    // Advance to where the first click's timer would have fired
    vi.advanceTimersByTime(1000); // Now at 2000ms total, but timer was reset
    expect(button.textContent?.trim()).toBe("Copied");
    expect(status.textContent).toBe("Copied");

    // Advance 1000ms more (total 3000ms, 2000ms after second click)
    vi.advanceTimersByTime(1000);
    expect(button.textContent?.trim()).toBe("Copy");
    expect(status.textContent).toBe("");
  });
});
