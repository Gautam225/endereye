/** Same rule as the backend: "Sales 2026 (final).csv" -> "sales_2026_final". */
export function suggestTableName(fileName: string): string {
  const stem = fileName.replace(/\.[^.]+$/, "");
  const name =
    stem
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 63) || "table";
  return /^\d/.test(name) ? `t_${name}`.slice(0, 63) : name;
}
