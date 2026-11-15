"use client";

import { useEffect, useState } from "react";
import { Brain } from "lucide-react";
import { api } from "@/lib/api";

export function MemoryStrip({ refreshKey }: { refreshKey: number }) {
  const [m, setM] = useState<{ outcomes: number; lessons: string } | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { api.memory().then(setM).catch(() => setM(null)); }, [refreshKey]);
  if (!m) return null;
  const lines = m.lessons.split("\n").filter((l) => l.startsWith("- "));
  return (
    <div className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hairline hover:text-foreground">
        <Brain className="size-3.5" aria-hidden />Memory · <span className="num text-foreground">{m.outcomes}</span> past outcomes
      </button>
      {open && (
        <div role="dialog" aria-label="What Reclaim remembers" className="absolute right-0 top-full z-20 mt-2 w-[min(28rem,90vw)] rounded-xl bg-popover p-4 hairline">
          <p className="eyebrow mb-2">Lessons from past disputes</p>
          {lines.length === 0 ? <p className="text-sm text-muted-foreground">Nothing yet. Record the result of a sent dispute and it will show up here.</p>
            : <ul className="scroll-quiet max-h-64 space-y-2 overflow-y-auto text-sm">{lines.map((l, i) => <li key={i} className="text-muted-foreground">{l.slice(2)}</li>)}</ul>}
        </div>
      )}
    </div>
  );
}
