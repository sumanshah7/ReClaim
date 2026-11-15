import { confidenceTier } from "@/lib/format";
import { cn } from "@/lib/utils";

const TIER = {
  high: { label: "High", bar: "bg-foreground", text: "text-foreground" },
  medium: { label: "Medium", bar: "bg-foreground/60", text: "text-foreground/80" },
  low: { label: "Low", bar: "bg-caution", text: "text-caution" },
} as const;

export function ConfidenceBadge({ value, className }: { value: number; className?: string }) {
  const t = TIER[confidenceTier(value)];
  return (
    <span className={cn("inline-flex items-center gap-2 rounded-md px-2 py-1 hairline bg-raised/60", className)} title={`Confidence ${value} of 100`}>
      <span className="relative h-1 w-8 overflow-hidden rounded-full bg-border" aria-hidden>
        <span className={cn("absolute inset-y-0 left-0 rounded-full transition-[width] duration-500", t.bar)} style={{ width: `${value}%` }} />
      </span>
      <span className={cn("num font-mono text-[11px] font-medium", t.text)}>{value}</span>
      <span className={cn("text-[11px]", t.text)}>{t.label}</span>
    </span>
  );
}
