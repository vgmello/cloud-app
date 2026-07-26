import { getById } from "../lib/dom";

const RESET_MS = 2000;
const FAILURE_MESSAGE = "Copy failed — select the code and copy manually";

type CopyOutcome = "success" | "failure";

export function initCopy(
  root: ParentNode = document,
  clipboard: Pick<Clipboard, "writeText"> = navigator.clipboard,
): void {
  const liveRegion = root.querySelector<HTMLElement>("[data-copy-status]");

  for (const button of root.querySelectorAll<HTMLButtonElement>(
    "[data-copy-target]",
  )) {
    const targetId = button.dataset.copyTarget;
    const target = targetId ? getById(root, targetId) : null;
    if (!target) continue;

    button.hidden = false;
    const label = button.textContent ?? "Copy";
    let timer: ReturnType<typeof setTimeout> | undefined;
    let writeInFlight = false;

    button.addEventListener("click", () => {
      if (writeInFlight) return;
      writeInFlight = true;
      void clipboard
        .writeText(target.textContent ?? "")
        .then(() => announce("success"))
        .catch(() => announce("failure"))
        .finally(() => {
          writeInFlight = false;
        });
    });

    function announce(outcome: CopyOutcome): void {
      const message = outcome === "success" ? "Copied" : FAILURE_MESSAGE;
      button.textContent = outcome === "success" ? "Copied" : "Failed";
      if (liveRegion) liveRegion.textContent = message;
      clearTimeout(timer);
      timer = setTimeout(() => {
        button.textContent = label;
        if (liveRegion) liveRegion.textContent = "";
      }, RESET_MS);
    }
  }
}
