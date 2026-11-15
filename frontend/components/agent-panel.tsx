"use client";

import { useEffect, useMemo, useRef } from "react";
import { AnimatePresence, motion } from "motion/react";
import { CheckCircle2, Circle, CircleDot, GitBranch, Hand, Wrench } from "lucide-react";
import type { AgentEvent, RunState } from "@/lib/api";
import { cn } from "@/lib/utils";

type Todo = { content: string; state: "pending" | "active" | "done" };

const CASE_RE = /(?:doordash|ubereats):[A-Za-z0-9-]+/;
const TOOL_LABEL: Record<string, string> = {
  load_payout: "Read the payout report", triage_cases: "Ranked the queue", read_memory: "Checked memory",
  recall_similar_cases: "Recalled similar past cases", get_case: "Opened the case", read_ticket_image: "Read the order ticket",
  check_ticket_vs_claim: "Compared the claim to the ticket", check_pickup_timestamps: "Checked pickup timestamps",
  check_repeat_claimant: "Checked for repeat claims", lint_dispute: "Checked the wording", submit_dispute: "Submitted the draft for approval",
  send_dispute: "Sent the approved dispute", record_outcome: "Recorded the outcome",
};

function deriveTodos(events: AgentEvent[]): Todo[] {
  const plan = [...events].reverse().find((e) => e.type === "plan");
  if (!plan) return [];
  const active = new Map<string, "active" | "done">(); // `${agent}:${caseId}`
  let current: string | null = null;
  for (const e of events) {
    if (e.type !== "subagent") continue;
    if (e.payload.state === "started") {
      const cid = String(e.payload.task ?? "").match(CASE_RE)?.[0];
      current = cid ? `${e.payload.agent}:${cid}` : null;
      if (current) active.set(current, "active");
    } else if (current) { active.set(current, "done"); current = null; }
  }
  const sent = new Set(events.filter((e) => e.type === "todo_update" && e.payload.status === "sent").map((e) => e.payload.case_id));
  return (plan.payload.todos as { content: string; status: string }[]).map((t) => {
    const cid = t.content.match(CASE_RE)?.[0];
    const agent = /investigat|evidence|gather/i.test(t.content) ? "evidence" : /draft|dispute/i.test(t.content) && !/send/i.test(t.content) ? "dispute-writer" : null;
    let state: Todo["state"] = t.status === "completed" ? "done" : t.status === "in_progress" ? "active" : "pending";
    if (state === "pending" && cid && agent) state = active.get(`${agent}:${cid}`) ?? "pending";
    if (cid && /send/i.test(t.content) && sent.has(cid)) state = "done";
    return { content: t.content, state };
  });
}

function Line({ e }: { e: AgentEvent }) {
  const p = e.payload;
  if (e.type === "replan") {
    return (
      <div className="rounded-lg border border-caution/40 bg-caution/10 p-3">
        <p className="flex items-center gap-2 text-sm font-medium text-caution"><GitBranch className="size-4" />Re-planned</p>
        <p className="mt-1 text-sm">{String(p.case_id).split(":")[1]} moved from #{p.from_rank} to #{p.to_rank}. {p.reason}</p>
        <p className="mt-1 text-xs text-muted-foreground">{String(p.promoted_case_id).split(":")[1]} was promoted.</p>
      </div>
    );
  }
  if (e.type === "interrupt") {
    return <div className="rounded-lg bg-money-dim p-3"><p className="flex items-center gap-2 text-sm font-medium text-money"><Hand className="size-4" />Waiting for you</p><p className="mt-1 text-sm">Review {String(p.case_id).split(":")[1]} and approve, edit or skip.</p></div>;
  }
  if (e.type === "subagent") {
    return <p className="text-sm"><span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{p.state === "started" ? `${p.agent} agent` : "result"}</span><br />{p.state === "started" ? String(p.task) : String(p.result).split("\n")[0]}</p>;
  }
  if (e.type === "tool_call") {
    return <p className="flex items-center gap-2 text-xs text-muted-foreground"><Wrench className="size-3 shrink-0" aria-hidden />{TOOL_LABEL[p.tool] ?? p.tool}{p.args?.case_id ? <span className="font-mono">· {String(p.args.case_id).split(":")[1]}</span> : null}</p>;
  }
  if (e.type === "done") return <p className="text-sm text-muted-foreground">Finished. {p.summary ? String(p.summary).slice(0, 220) : ""}</p>;
  if (e.type === "error") return <p className="text-sm text-danger">Stopped: {String(p.message).slice(0, 160)}</p>;
  return null;
}

export function AgentPanel({ events, state }: { events: AgentEvent[]; state: RunState | null }) {
  const todos = useMemo(() => deriveTodos(events), [events]);
  const log = useMemo(() => events.filter((e) => ["replan", "interrupt", "subagent", "tool_call", "done", "error"].includes(e.type)), [events]);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [log.length]);
  const status = state?.status ?? "running";
  const label = { running: "Working", waiting_approval: "Waiting for you", done: "Finished", error: "Stopped" }[status];

  return (
    <aside aria-label="Live agent activity" className="flex min-h-0 flex-col rounded-xl bg-card hairline">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 className="eyebrow">Agent</h2>
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className={cn("size-2 rounded-full", status === "running" ? "live-dot bg-money" : status === "waiting_approval" ? "bg-money" : status === "error" ? "bg-danger" : "bg-muted-foreground")} aria-hidden />{label}
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col" aria-live="polite">
        <section className="scroll-quiet max-h-[40%] shrink-0 overflow-y-auto border-b border-border p-5">
          <h3 className="eyebrow mb-2">Plan</h3>
          {todos.length === 0 ? <p className="text-sm text-muted-foreground">Planning…</p> : (
            <ul className="space-y-1.5">
              <AnimatePresence initial={false}>
                {todos.map((t) => (
                  <motion.li key={t.content} layout initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} className="flex items-start gap-2 text-sm">
                    {t.state === "done" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-money" /> : t.state === "active" ? <CircleDot className="mt-0.5 size-4 shrink-0 text-foreground" /> : <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground/60" />}
                    <span className={cn(t.state === "done" && "text-muted-foreground line-through decoration-muted-foreground/40", t.state === "pending" && "text-muted-foreground")}>{t.content}</span>
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          )}
        </section>
        <section className="scroll-quiet min-h-0 flex-1 overflow-y-auto p-5">
          <h3 className="eyebrow mb-2">Activity</h3>
          <div className="space-y-2.5">
            {log.map((e) => <motion.div key={e.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18 }}><Line e={e} /></motion.div>)}
            <div ref={end} />
          </div>
        </section>
      </div>
    </aside>
  );
}
