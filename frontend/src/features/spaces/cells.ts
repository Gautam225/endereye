// The lookahead stops "INTERVAL" matching "INT", and "INTEGER[]" (a list) matching "INTEGER".
const NUMERIC = /^(U?(TINY|SMALL|BIG|HUGE)?INT(EGER)?|DOUBLE|FLOAT|REAL|DECIMAL)(?![\w[])/i;
const TEMPORAL = /^(DATE|TIMESTAMP(_S|_MS|_NS)?|TIME|DATETIME)(?![\w[])/i;

/** Whether a column of this database type holds numbers (so it is right-aligned and chartable). */
export function isNumericType(type: string): boolean {
  return NUMERIC.test(type);
}

export function isTemporalType(type: string): boolean {
  return TEMPORAL.test(type);
}

/** How one value appears in a result table. Nothing is rounded or changed. */
export function formatCell(value: unknown): { text: string; isNull: boolean } {
  if (value === null || value === undefined) return { text: "null", isNull: true };
  if (typeof value === "object") return { text: JSON.stringify(value), isNull: false };
  return { text: String(value), isNull: false };
}

const grouped = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

/**
 * A value as a person reads it: numbers with thousands separators, dates without a midnight time.
 * The exact stored value is kept for the tooltip (the function above), so nothing is hidden.
 */
export function formatValue(value: unknown, type: string): { text: string; isNull: boolean } {
  const plain = formatCell(value);
  if (plain.isNull) return plain;
  if (typeof value === "number" && isNumericType(type) && Number.isFinite(value)) {
    return { text: grouped.format(value), isNull: false };
  }
  if (typeof value === "string" && isTemporalType(type)) {
    const trimmed = value.replace(/^(\d{4}-\d{2}-\d{2})T00:00:00(\.0+)?$/, "$1");
    return {
      text: trimmed
        .replace("T", " ")
        .replace(/(\.\d*?)0+$/, "$1")
        .replace(/\.$/, ""),
      isNull: false,
    };
  }
  return plain;
}

/** Ordering for sorting a column: numbers by value, other values as text, empty values last. */
export function compareValues(a: unknown, b: unknown, type: string): number {
  const aEmpty = a === null || a === undefined;
  const bEmpty = b === null || b === undefined;
  if (aEmpty || bEmpty) return Number(aEmpty) - Number(bEmpty);
  if (isNumericType(type)) {
    const x = Number(a);
    const y = Number(b);
    if (Number.isFinite(x) && Number.isFinite(y)) return x - y;
  }
  return String(a).localeCompare(String(b), "en", { numeric: true, sensitivity: "base" });
}
