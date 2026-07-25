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
          ? container.querySelector<HTMLElement>(
              `#${source.dataset.connectFrom}`,
            )
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
    window.addEventListener("resize", draw, { passive: true });

    // `draw()` above runs synchronously right after `initReveal` applies
    // `will-reveal` (opacity: 0; translateY(12px)), so the first pass bakes
    // in pre-reveal coordinates. Once the reveal transition on a child
    // finishes — settling it at its resting position — `transitionend`
    // bubbles up to this container and we redraw with correct coordinates.
    // Under reduced motion `initReveal` never applies `will-reveal` (it
    // jumps straight to `is-revealed`), so there is no layout change and no
    // transition to wait for; the initial `draw()` is already correct.
    container.addEventListener("transitionend", draw);
  }
}
