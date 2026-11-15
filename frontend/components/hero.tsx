"use client";

import { useEffect, useRef, useState } from "react";
import { CalendarClock } from "lucide-react";
import type { Hero as HeroT } from "@/lib/api";
import { deadlineLabel, shortDate, usd } from "@/lib/format";
import { Skeleton } from "@/components/ui/skeleton";

function useTween(target: number) {
  const [v, setV] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = from.current, t0 = performance.now(), dur = 700;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || start === target) { setV(target); from.current = target; return; }
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      const cur = Math.round(start + (target - start) * e);
      setV(cur); from.current = cur;
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return v;
}

export function Hero({ hero, loading }: { hero: HeroT | null; loading: boolean }) {
  const shown = useTween(hero?.recoverable_cents ?? 0);
  const urgent = hero?.next_deadline_days != null && hero.next_deadline_days <= 3;
  return (
    <section aria-label="Money recoverable this week" className="grid gap-6 rounded-xl hairline bg-card p-6 md:grid-cols-[1fr_auto] md:items-end md:p-8">
      <div>
        <p className="eyebrow">Recoverable this week · expected value</p>
        {loading || !hero ? (
          <Skeleton className="mt-3 h-20 w-72" />
        ) : (
          <p className="num mt-2 text-6xl font-semibold leading-none text-money md:text-8xl" aria-live="polite">{usd(shown)}</p>
        )}
        {hero && (
          <p className="mt-3 text-sm text-muted-foreground">
            across <span className="num text-foreground">{hero.workable_cases}</span> workable cases ·{" "}
            <span className="num text-foreground">{usd(hero.gross_cents)}</span> deducted in total. Estimates, not guarantees.
          </p>
        )}
      </div>
      <div className="flex items-center gap-3 rounded-lg bg-raised px-4 py-3 hairline md:min-w-64">
        <CalendarClock className={urgent ? "size-5 text-caution" : "size-5 text-muted-foreground"} aria-hidden />
        {loading || !hero ? <Skeleton className="h-9 w-36" /> : hero.next_deadline ? (
          <div>
            <p className="eyebrow">Next filing deadline</p>
            <p className="num text-lg font-medium">{shortDate(hero.next_deadline)} <span className={urgent ? "text-caution" : "text-muted-foreground"}>· {deadlineLabel(hero.next_deadline_days)}</span></p>
          </div>
        ) : <p className="text-sm text-muted-foreground">No open deadlines</p>}
      </div>
    </section>
  );
}
