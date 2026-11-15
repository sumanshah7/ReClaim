"use client";

import { useCallback, useRef, useState } from "react";
import { CircleHelp } from "lucide-react";
import { useEscape } from "@/hooks/use-escape";

const STEPS = [
  { who: "Orchestrator", what: "The main Deep Agent. Reads the report, makes a to-do list, hands each case to a specialist, and rewrites the list when something turns out weak. It never files anything." },
  { who: "Evidence agent", what: "A subagent with its own instructions and tools. Reads the ticket, checks it against the claim, the pickup times and repeat claims, writes a note to the file system, and returns a verdict." },
  { who: "Dispute-writer agent", what: "A second subagent. Gets only the facts and evidence ids, writes a neutral dispute, and has it checked for wording and evidence before you see it." },
  { who: "You", what: "The agent pauses and waits. Nothing is approved until you say so." },
];

/** Plain-language map of the agents, for someone who has never seen LangChain's Deep Agents. */
export function HowItWorks() {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useEscape(open, close, btn);
  return (
    <div className="relative">
      <button ref={btn} onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground">
        <CircleHelp className="size-3.5" aria-hidden />How it works
      </button>
      {open && (
        <div role="dialog" aria-label="How the agents work" className="absolute right-0 top-full z-30 mt-2 w-[min(23rem,86vw)] rounded-xl bg-popover p-4 hairline">
          <p className="eyebrow">Built with LangChain Deep Agents</p>
          <ol className="mt-3 space-y-3">
            {STEPS.map((s, i) => (
              <li key={s.who} className="flex gap-3">
                <span className="num mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] hairline">{i + 1}</span>
                <p className="text-sm"><span className="font-medium">{s.who}.</span> <span className="text-muted-foreground">{s.what}</span></p>
              </li>
            ))}
          </ol>
          <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
            Why subagents? Each case is judged in a fresh, separate context, so one case can&apos;t bleed into another and the main agent stays uncluttered.
            Money, dates and scoring are plain code, not the model. Open <span className="text-foreground">Agent files</span> to see what the agents wrote.
          </p>
        </div>
      )}
    </div>
  );
}
