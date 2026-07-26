const RESET_MS = 2000;
const FAILURE_MESSAGE = "Copy failed — select the code and copy manually";

export function initCopy(
  root: ParentNode = document,
  clipboard: Pick<Clipboard, "writeText"> = navigator.clipboard,
): void {
  const status = root.querySelector<HTMLElement>("[data-copy-status]");

  for (const button of root.querySelectorAll<HTMLButtonElement>(
    "[data-copy-target]",
  )) {
    const targetId = button.dataset.copyTarget;
    const target = targetId
      ? root.querySelector<HTMLElement>(`#${targetId}`)
      : null;
    if (!target) continue;

    button.hidden = false;
    const label = button.textContent ?? "Copy";
    let timer: ReturnType<typeof setTimeout> | undefined;

    button.addEventListener("click", () => {
      void clipboard
        .writeText(target.textContent ?? "")
        .then(() => announce("Copied"))
        .catch(() => announce(FAILURE_MESSAGE));
    });

    function announce(message: string): void {
      button.textContent = message === "Copied" ? "Copied" : "Failed";
      if (status) status.textContent = message;
      clearTimeout(timer);
      timer = setTimeout(() => {
        button.textContent = label;
        if (status) status.textContent = "";
      }, RESET_MS);
    }
  }
}
