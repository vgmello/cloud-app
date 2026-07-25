const ENTITIES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ENTITIES[char] ?? char);
}

/**
 * Joins a template into markup. Values are inserted raw so sections can nest
 * each other's output; anything user-visible that is not markup (code samples,
 * copy) must be passed through escapeHtml by the caller.
 */
export function html(
  strings: TemplateStringsArray,
  ...values: unknown[]
): string {
  return strings.reduce<string>((out, chunk, index) => {
    if (index === 0) return chunk;
    const value = values[index - 1];
    return (
      out + (Array.isArray(value) ? value.join("") : String(value)) + chunk
    );
  }, "");
}
