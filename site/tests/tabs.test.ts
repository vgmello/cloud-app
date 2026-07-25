import { beforeEach, describe, expect, it } from "vitest";
import { initTabs } from "../src/behaviors/tabs";

function setup(): { tabs: HTMLButtonElement[]; panels: HTMLElement[] } {
  document.body.innerHTML = `
    <div data-tabs>
      <div role="tablist">
        <button type="button" role="tab" id="tab-a" aria-controls="panel-a" aria-selected="true" tabindex="0">A</button>
        <button type="button" role="tab" id="tab-b" aria-controls="panel-b" aria-selected="false" tabindex="-1">B</button>
      </div>
      <div id="panel-a" role="tabpanel" aria-labelledby="tab-a">first</div>
      <div id="panel-b" role="tabpanel" aria-labelledby="tab-b" hidden>second</div>
    </div>
  `;
  initTabs(document);
  return {
    tabs: [...document.querySelectorAll<HTMLButtonElement>('[role="tab"]')],
    panels: [...document.querySelectorAll<HTMLElement>('[role="tabpanel"]')],
  };
}

function press(tab: HTMLElement, key: string): void {
  tab.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
}

describe("initTabs", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("shows the panel of the clicked tab and hides the others", () => {
    const { tabs, panels } = setup();
    tabs[1]?.click();
    expect(panels[0]?.hidden).toBe(true);
    expect(panels[1]?.hidden).toBe(false);
    expect(tabs[1]?.getAttribute("aria-selected")).toBe("true");
    expect(tabs[0]?.getAttribute("aria-selected")).toBe("false");
  });

  it("keeps exactly one tab in the tab order", () => {
    const { tabs } = setup();
    tabs[1]?.click();
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([-1, 0]);
  });

  it("moves selection with ArrowRight and wraps around", () => {
    const { tabs, panels } = setup();
    press(tabs[0]!, "ArrowRight");
    expect(panels[1]?.hidden).toBe(false);
    press(tabs[1]!, "ArrowRight");
    expect(panels[0]?.hidden).toBe(false);
  });

  it("moves selection with ArrowLeft, Home, and End", () => {
    const { tabs, panels } = setup();
    press(tabs[0]!, "End");
    expect(panels[1]?.hidden).toBe(false);
    press(tabs[1]!, "Home");
    expect(panels[0]?.hidden).toBe(false);
    press(tabs[0]!, "ArrowLeft");
    expect(panels[1]?.hidden).toBe(false);
  });

  it("focuses the tab reached by keyboard but not the one reached by click", () => {
    const { tabs } = setup();
    press(tabs[0]!, "ArrowRight");
    expect(document.activeElement).toBe(tabs[1]);
    tabs[0]?.click();
    expect(document.activeElement).toBe(tabs[1]);
  });

  it("ignores unrelated keys", () => {
    const { tabs, panels } = setup();
    press(tabs[0]!, "a");
    expect(panels[0]?.hidden).toBe(false);
  });

  it("does nothing when there is no tab group", () => {
    document.body.innerHTML = "<div>no tabs here</div>";
    expect(() => initTabs(document)).not.toThrow();
  });
});
