/**
 * Display formatting.
 *
 * Centralised so a timestamp reads identically on every surface — a log that
 * shows "2m ago" in one table and "31/07/2026 19:41" in the next makes the
 * product feel assembled from parts.
 */

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", 7],
  ["week", 4.34524],
  ["month", 12],
  ["year", Number.POSITIVE_INFINITY],
];

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/**
 * "2 minutes ago". Pair with a `title` carrying the absolute timestamp —
 * relative time is scannable, absolute time is what gets quoted in a ticket.
 */
export function relativeTime(iso: string): string {
  const elapsed = (Date.now() - new Date(iso).getTime()) / 1000;
  if (Number.isNaN(elapsed)) return "—";
  if (elapsed < 45) return "just now";

  let value = elapsed;
  for (const [unit, step] of UNITS) {
    if (Math.abs(value) < step) return relative.format(-Math.round(value), unit);
    value /= step;
  }
  return relative.format(-Math.round(value), "year");
}

export function absoluteTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function compactNumber(value: number): string {
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(
    value,
  );
}

/** Escape a CSV cell. Quotes are doubled; anything risky is quoted. */
export function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function toCsv(rows: Record<string, unknown>[], columns: string[]): string {
  const header = columns.map(csvCell).join(",");
  const body = rows.map((row) => columns.map((key) => csvCell(row[key])).join(","));
  return [header, ...body].join("\n");
}

/** Trigger a client-side download without a server round-trip. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
