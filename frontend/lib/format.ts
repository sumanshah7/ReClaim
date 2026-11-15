export const usd = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);

export const platformLabel = (p: string) => ({ doordash: "DoorDash", ubereats: "Uber Eats", grubhub: "Grubhub" } as Record<string, string>)[p] ?? p;

export const reasonLabel = (r: string) => r.replace(/_/g, " ");

export function deadlineLabel(days: number | null | undefined) {
  if (days == null) return "";
  if (days < 0) return `expired ${-days}d ago`;
  if (days === 0) return "due today";
  if (days === 1) return "1 day left";
  return `${days} days left`;
}

export function confidenceTier(c: number): "high" | "medium" | "low" {
  return c >= 70 ? "high" : c >= 45 ? "medium" : "low";
}

export const shortDate = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
