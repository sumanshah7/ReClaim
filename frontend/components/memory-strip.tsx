"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Brain } from "lucide-react";
import { api } from "@/lib/api";
import { useEscape } from "@/hooks/use-escape";

export function MemoryStrip({ refreshKey }: { refreshKey: number }) {
  const [m, setM] = useState<{ outcomes: number; lessons: string } | null>(null);
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useEscape(open, close, btn);
  useEffect(() => {
    // Outcomes can arrive from the text channel at any time, so poll lightly instead of relying on run events.
    let live = true;
    const pull = () => api.memory().then((x) => live && setM(x)).catch(() => live && setM(null));
    pull();
    const t = setInterval(pull, 2500);
    return () => { live = false; clearInterval(t); };
  }, [refreshKey]);
  if (!m) return null;
  const lines = m.lessons.split("\n").filter((l) => l.startsWith("- ")).reverse(); // newest first
  return (
    <div className="relative">
      <button ref={btn} onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hairline hover:text-foreground">
        <Brain className="size-3.5" aria-hidden />Memory · <span className="num text-foreground">{m.outcomes}</span> past outcomes
      </button>
      {open && (
        <div role="dialog" aria-label="What Reclaim remembers" className="absolute right-0 top-full z-20 mt-2 w-[min(28rem,90vw)] rounded-xl bg-popover p-4 hairline">
          <p className="eyebrow mb-2">Lessons from past disputes · newest first</p>
          {lines.length === 0 ? <p className="text-sm text-muted-foreground">Nothing yet. Record the result of a sent dispute and it will show up here.</p>
            : <ul className="scroll-quiet max-h-64 space-y-2 overflow-y-auto text-sm">{lines.map((l, i) => <li key={i} className="text-muted-foreground">{l.slice(2)}</li>)}</ul>}
        </div>
      )}
    </div>
  );
}
