import { getById } from "../lib/dom";

const SVG_NS = "http://www.w3.org/2000/svg";

export function initConnectors(root: ParentNode = document): void {
  for (const container of root.querySelectorAll<HTMLElement>(
    "[data-connectors]",
  )) {
    const canvas = container.querySelector<SVGSVGElement>(
      "[data-connector-canvas]",
    );
    if (!canvas) continue;

    const draw = (): void => {
      const frame = container.getBoundingClientRect();
      canvas.setAttribute("viewBox", `0 0 ${frame.width} ${frame.height}`);
      canvas.replaceChildren();

      const animate =
        typeof matchMedia !== "function" ||
        !matchMedia("(prefers-reduced-motion: reduce)").matches;

      for (const source of container.querySelectorAll<HTMLElement>(
        "[data-connect-from]",
      )) {
        const target = source.dataset.connectFrom
          ? getById(container, source.dataset.connectFrom)
          : null;
        if (!target) continue;

        const from = source.getBoundingClientRect();
        const to = target.getBoundingClientRect();
        const line = document.createElementNS(SVG_NS, "line");
        line.setAttribute("x1", String(from.right - frame.left));
        line.setAttribute("y1", String(from.top + from.height / 2 - frame.top));
        line.setAttribute("x2", String(to.left - frame.left));
        line.setAttribute("y2", String(to.top + to.height / 2 - frame.top));
        line.setAttribute(
          "class",
          animate ? "connector connector-draw" : "connector",
        );
        canvas.append(line);
      }
    };

    draw();

    // `draw()` above runs synchronously right after `initReveal` applies
    // `will-reveal` (opacity: 0; translateY(12px)), so the first pass bakes
    // in pre-reveal coordinates. Once the reveal transition on a child
    // finishes — settling it at its resting position — `transitionend`
    // bubbles up to this container and we redraw with correct coordinates.
    // Under reduced motion `initReveal` never applies `will-reveal` (it
    // jumps straight to `is-revealed`), so there is no layout change and no
    // transition to wait for; the initial `draw()` is already correct.
    //
    // A single reveal moves several descendants at once, and each one
    // transitions both `opacity` and `transform` — so one scroll produces a
    // burst of `transitionend` events on this container. Reacting to every
    // one of them would call `draw()` (which calls `replaceChildren()` and
    // re-adds `connector-draw`) repeatedly, restarting the line-draw
    // animation from zero each time and making the lines stutter. Only the
    // `transform` property actually moves anything `draw()` cares about, so
    // ignore `opacity` events.
    //
    // The remaining `transform` events are *not* bunched into one animation
    // frame: `applyStagger()` in reveal.ts staggers the `[data-reveal]`
    // descendants of this section by `STAGGER_MS` (60ms) each, so their
    // 620ms transitions finish roughly 60ms apart — each completion lands in
    // its own frame. A `requestAnimationFrame` coalescing flag only merges
    // events within the same ~16ms frame, so it would still call `draw()`
    // once per staggered element. Instead, use a trailing debounce: reset a
    // timer on every qualifying event, and only redraw once the events have
    // stopped arriving for a quiet period comfortably longer than the
    // 60ms stagger gap. That way one scroll produces exactly one redraw,
    // using the final settled geometry.
    //
    // `resize` shares this same debounce: a window drag can fire it far more
    // often than the display can usefully redraw, for the same reasons as
    // the staggered `transitionend` burst above.
    const REDRAW_DEBOUNCE_MS = 150;
    let redrawTimer: ReturnType<typeof setTimeout> | undefined;
    const scheduleRedraw = (): void => {
      if (redrawTimer !== undefined) clearTimeout(redrawTimer);
      redrawTimer = setTimeout(() => {
        redrawTimer = undefined;
        draw();
      }, REDRAW_DEBOUNCE_MS);
    };

    window.addEventListener("resize", scheduleRedraw, { passive: true });
    container.addEventListener("transitionend", (event) => {
      if (event.propertyName !== "transform") return;
      scheduleRedraw();
    });
  }
}
