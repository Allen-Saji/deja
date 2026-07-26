export function formatDuration(milliseconds: number | null): string {
  if (milliseconds === null) {
    return "pending";
  }
  if (milliseconds < 1_000) {
    return `${milliseconds} ms`;
  }
  return `${(milliseconds / 1_000).toFixed(milliseconds >= 10_000 ? 1 : 2)} s`;
}

export function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(new Date(value));
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function compactIdentifier(value: string): string {
  const [prefix, body = ""] = value.split("-", 2);
  return `${prefix}-${body.slice(0, 6)}`;
}

export function humanize(value: string | null): string {
  if (!value) {
    return "None";
  }
  return value.replaceAll("_", " ").replaceAll("-", " ");
}
