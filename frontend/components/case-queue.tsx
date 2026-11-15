"use client";

import { LayoutGroup, motion } from "motion/react";
import { AlertTriangle, CircleCheck, Hourglass, Send, SkipForward } from "lucide-react";
import type { CaseRow } from "@/lib/api";
import { deadlineLabel, platformLabel, reasonLabel, usd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ConfidenceBadge } from "@/components/confidence-badge";

function StatusChip({ c, pending }: { c: CaseRow; pending: boolean }) {
  const base = "inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider";
  if (pending) return <span className={cn(base, "bg-money text-primary-foreground font-semibold")}><Hourglass className="size-3" />Needs you</span>;
  if (c.status === "sent") return <span className={cn(base, "bg-money-dim text-money")}><Send className="size-3" />Sent</span>;
  if (c.status === "skipped") return <span className={cn(base, "text-muted-foreground hairline")}><SkipForward className="size-3" />Skipped</span>;
  if (c.status === "awaiting_approval") return <span className={cn(base, "text-foreground hairline")}><CircleCheck className="size-3" />Drafted</span>;
  if (c.recommend_skip) return <span className={cn(base, "text-muted-foreground hairline")}>Skip advised</span>;
  if (c.weak) return <span className={cn(base, "text-caution hairline")}><AlertTriangle className="size-3" />Weak</span>;
  if (c.status === "investigating") return <span className={cn(base, "text-muted-foreground hairline")}>Investigating</span>;
  return <span className={cn(base, "text-muted-foreground hairline")}>Queued</span>;
}

export function CaseQueue({ cases, selected, pendingCase, onSelect }: {
  cases: CaseRow[]; selected: string | null; pendingCase: string | null; onSelect: (id: string) => void;
}) {
  return (
    <section aria-label="Case queue" className="flex min-h-0 flex-col">
      <div className="mb-3 flex items-baseline justify-between px-1">
        <h2 className="eyebrow">Case queue</h2>
        <p className="text-xs text-muted-foreground">by expected value, then deadline</p>
      </div>
      <LayoutGroup>
        <ol className="scroll-quiet -mx-1 flex min-h-0 flex-col gap-2 overflow-y-auto px-1 pb-2">
          {cases.map((c) => {
            const active = c.case_id === selected;
            const dim = c.recommend_skip || c.status === "skipped";
            return (
              <motion.li layout="position" key={c.case_id} transition={{ type: "spring", stiffness: 380, damping: 36 }}>
                <button
                  onClick={() => onSelect(c.case_id)}
                  aria-pressed={active}
                  className={cn(
                    "group w-full rounded-lg bg-card p-3.5 text-left transition-colors hairline hover:bg-raised focus-visible:outline-2 focus-visible:outline-ring",
                    active && "bg-raised ring-1 ring-money/50",
                    dim && "opacity-60",
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="num font-mono text-xs text-muted-foreground">#{c.rank}</span>
                        <span className="truncate font-mono text-sm">{c.order_id}</span>
                      </div>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {platformLabel(c.platform)} · {reasonLabel(c.reason)}{c.claimed_item ? ` · ${c.claimed_item}` : ""}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className={cn("num text-lg font-semibold leading-none", dim ? "text-muted-foreground" : "text-money")}>{usd(c.expected_cents)}</p>
                      <p className="num mt-1 text-[11px] text-muted-foreground">of {c.amount} deducted</p>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <ConfidenceBadge value={c.confidence} />
                    <StatusChip c={c} pending={c.case_id === pendingCase} />
                    <span className={cn("ml-auto text-[11px]", c.days_left <= 3 ? "text-caution" : "text-muted-foreground")}>{deadlineLabel(c.days_left)}</span>
                  </div>
                </button>
              </motion.li>
            );
          })}
        </ol>
      </LayoutGroup>
    </section>
  );
}
