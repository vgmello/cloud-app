/**
 * Resolves an element by id from any `ParentNode` without interpolating the
 * id into a CSS selector string. `root.querySelector('#' + id)` breaks (or
 * worse, silently matches the wrong element) whenever `id` contains a
 * character that is meaningful in a CSS selector — a colon, a space, a
 * leading digit. Ids on this page are generated slugs today, so the risk is
 * theoretical, but resolving by id should never depend on the id happening
 * to already look like a bare CSS identifier.
 */
export function getById(root: ParentNode, id: string): HTMLElement | null {
  if (root instanceof Document || root instanceof DocumentFragment) {
    return root.getElementById(id);
  }
  for (const element of root.querySelectorAll<HTMLElement>("[id]")) {
    if (element.id === id) return element;
  }
  return null;
}
