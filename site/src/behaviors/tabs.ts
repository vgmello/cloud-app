const KEY_DELTA: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1 };

export function initTabs(root: ParentNode = document): void {
  for (const group of root.querySelectorAll<HTMLElement>("[data-tabs]")) {
    setupGroup(group);
  }
}

function setupGroup(group: HTMLElement): void {
  const tabs = [...group.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  const panels = [...group.querySelectorAll<HTMLElement>('[role="tabpanel"]')];
  if (tabs.length === 0) return;

  const select = (index: number, moveFocus: boolean): void => {
    tabs.forEach((tab, position) => {
      const active = position === index;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active && moveFocus) tab.focus();
    });
    panels.forEach((panel, position) => {
      panel.hidden = position !== index;
    });
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => select(index, false));
    tab.addEventListener("keydown", (event) => {
      const target =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? tabs.length - 1
            : KEY_DELTA[event.key] === undefined
              ? -1
              : (index + KEY_DELTA[event.key]! + tabs.length) % tabs.length;
      if (target < 0) return;
      event.preventDefault();
      select(target, true);
    });
  });

  const selected = tabs.findIndex(
    (tab) => tab.getAttribute("aria-selected") === "true",
  );
  select(selected < 0 ? 0 : selected, false);
}
