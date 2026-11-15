"use client";

import { useState } from "react";
import Image from "next/image";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Brain, Check, CircleAlert, GitBranch, CircleCheck, CircleMinus, FileQuestion, Pencil, SkipForward } from "lucide-react";
import { api, type CaseDetail as Detail } from "@/lib/api";
import { deadlineLabel, platformLabel, reasonLabel, usd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ConfidenceBadge } from "@/components/confidence-badge";
import { PacketPanel } from "@/components/packet-panel";

function Ticket({ d }: { d: Detail }) {
  if (!d.ticket) {
    return (
      <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-card p-6 text-center">
        <FileQuestion className="size-7 text-caution" aria-hidden />
        <div>
          <p className="font-medium">No ticket on file for {d.order_id}</p>
          <p className="mt-1 text-sm text-muted-foreground">Without the order ticket there is nothing to check the claim against, so this case stays weak. A photo of the ticket would change that.</p>
        </div>
      </div>
    );
  }
  return (
    <figure className="overflow-hidden rounded-xl bg-card hairline">
      <div className="perforated" aria-hidden />
      <Image src={d.ticket.image_url} alt={`Order ticket for ${d.order_id}, listing ${d.ticket.items.join(", ")}`} width={420} height={360} unoptimized className="h-auto w-full bg-white" />
      <figcaption className="space-y-1.5 p-4">
        <p className="eyebrow">Read from ticket</p>
        <ul className="text-sm">
          {d.ticket.items.map((it) => (
            <li key={it} className="flex items-center justify-between gap-2 py-0.5">
              <span>{it}</span>
              {d.claimed_item && it.toLowerCase() === d.claimed_item.toLowerCase() && <span className="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground hairline">claimed</span>}
            </li>
          ))}
        </ul>
        {d.claimed_item && !d.ticket.items.some((i) => i.toLowerCase() === d.claimed_item!.toLowerCase()) && (
          <p className="text-sm text-muted-foreground">Claimed item <span className="text-foreground">“{d.claimed_item}”</span> is not on this ticket.</p>
        )}
      </figcaption>
    </figure>
  );
}

function EvidenceRow({ e }: { e: Detail["evidence"][number] }) {
  const Icon = e.supports > 0 ? CircleCheck : e.supports < 0 ? CircleAlert : CircleMinus;
  const tone = e.supports > 0 ? "text-foreground" : e.supports < 0 ? "text-danger" : "text-caution";
  return (
    <li className="flex gap-3 py-3">
      <Icon className={cn("mt-0.5 size-4 shrink-0", tone)} aria-label={e.supports > 0 ? "supports your position" : e.supports < 0 ? "works against you" : "missing or neutral"} />
      <div className="min-w-0">
        <p className="text-sm">{e.summary}</p>
        <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{e.id} · source {e.source}</p>
      </div>
    </li>
  );
}

function OutcomeForm({ runId, d, onSaved }: { runId: string; d: Detail; onSaved: () => void }) {
  const [saved, setSaved] = useState(false);
  const [lesson, setLesson] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (result: "won" | "lost") => {
    setBusy(true);
    try { await api.outcome(runId, d.case_id, { result, recovered_cents: result === "won" ? Math.round(parseFloat(d.amount.replace(/[$,]/g, "")) * 100) : 0, lesson }); setSaved(true); onSaved(); }
    finally { setBusy(false); }
  };
  if (saved) return <p className="text-sm text-muted-foreground">Saved to memory. Similar cases will be scored with this result.</p>;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Once the platform replies, record the result here (or text WON 28.40 / LOST) so Re-Claim learns from similar cases.</p>
      <Textarea value={lesson} onChange={(e) => setLesson(e.target.value)} placeholder="Optional: one factual line about what mattered" rows={2} aria-label="Lesson" />
      <div className="flex gap-2">
        <Button size="sm" disabled={busy} onClick={() => save("won")}>Won</Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => save("lost")}>Lost</Button>
      </div>
    </div>
  );
}

type Props = {
  runId: string; detail: Detail | null; loading: boolean; canDecide: boolean;
  onDecide: (d: "approve" | "edit" | "skip", body?: string) => Promise<void>; onMemoryChanged: () => void;
  holding?: boolean;                                           // the owner just approved this case: keep it in view
  next?: { orderId: string; onNext: () => void } | null;       // the next case waiting for a decision, offered explicitly
};

export function CaseDetail(props: Props) {
  const { detail, loading } = props;
  if (!detail) {
    return (
      <div className="grid min-h-96 place-items-center rounded-xl bg-card p-8 text-center hairline">
        {loading ? <Skeleton className="h-64 w-full" /> : <p className="text-sm text-muted-foreground">Select a case to see the ticket, the evidence and the agent’s reasoning.</p>}
      </div>
    );
  }
  // Remount when the case or its draft changes so editing state starts fresh (no state-sync effect needed).
  return <CaseDetailBody key={`${detail.case_id}:${detail.draft ?? ""}`} {...props} detail={detail} />;
}

function CaseDetailBody({ runId, detail, canDecide, onDecide, onMemoryChanged, holding, next }: Props & { detail: Detail }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(detail.draft ?? "");
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const d = detail;
  const act = async (kind: "approve" | "edit" | "skip") => {
    setBusy(true); setErrors([]);
    try { await onDecide(kind, kind === "edit" ? text : undefined); }
    catch (e) {
      const m = e instanceof Error ? e.message : "Could not save your decision.";
      try { const parsed = JSON.parse(m); setErrors(parsed.errors ?? [m]); } catch { setErrors([m]); }
    } finally { setBusy(false); }
  };
  const changed = text.trim() !== (d.draft ?? "").trim();
  const final = d.status === "sent" || d.status === "skipped";

  return (
    <motion.article key={d.case_id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22 }} className="space-y-5">
      {d.weak && <Replanned d={d} />}
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">{platformLabel(d.platform)} · {reasonLabel(d.reason)}</p>
          <h2 className="mt-1 font-mono text-2xl">{d.order_id}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{d.claimed_item ?? "No item named"} · {d.amount} deducted · {deadlineLabel(d.days_left)}</p>
        </div>
        <div className="text-right">
          <p className="eyebrow">Expected recovery</p>
          <p className="num text-4xl font-semibold leading-none text-money">{usd(d.expected_cents)}</p>
          <div className="mt-2 flex items-center justify-end gap-2"><span className="num text-sm text-muted-foreground">{d.win_probability_pct}% win estimate</span><ConfidenceBadge value={d.confidence} /></div>
        </div>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <Ticket d={d} />
        <div className="min-w-0 space-y-5">
          <section className="rounded-xl bg-card p-5 hairline">
            <h3 className="eyebrow">Why this score</h3>
            <ul className="mt-3 space-y-2 text-sm">
              {d.reasons.map((r, i) => <li key={i} className="flex gap-2"><span className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground" aria-hidden /><span>{r}</span></li>)}
            </ul>
            {d.memory && <MemoryReason m={d.memory} />}
            {d.recommend_skip && <Alert className="mt-4"><AlertDescription>Re-Claim recommends skipping this case: {d.skip_reason}</AlertDescription></Alert>}
          </section>
          <section className="rounded-xl bg-card p-5 hairline">
            <h3 className="eyebrow">Evidence <span className="text-muted-foreground">· only what was actually found</span></h3>
            {d.evidence.length === 0 ? <p className="mt-3 text-sm text-muted-foreground">The agent hasn’t gathered evidence for this case yet.</p>
              : <ul className="mt-1 divide-y divide-border">{d.evidence.map((e) => <EvidenceRow key={e.id} e={e} />)}</ul>}
          </section>
        </div>
      </div>

      <section className="rounded-xl bg-card p-5 hairline">
        <div className="flex items-center justify-between">
          <h3 className="eyebrow">Dispute draft</h3>
          {d.draft && <span className="text-xs text-muted-foreground">States facts only. Never accuses the customer.</span>}
        </div>
        {d.draft ? (
          editing ? <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={7} className="mt-3 text-sm leading-relaxed" aria-label="Edit dispute draft" />
            : <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{d.draft}</p>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">{d.weak ? "No dispute was drafted: the evidence is too thin, and Re-Claim won’t pad it." : d.recommend_skip ? "No dispute was drafted because skipping is recommended." : "A draft will appear here once the agent finishes this case."}</p>
        )}
        {d.draft && !canDecide && !final && <p className="mt-4 border-t border-border pt-4 text-sm text-muted-foreground">Drafted. Waiting for its turn to be shown to you.</p>}
        {d.status === "skipped" && <p className="mt-4 border-t border-border pt-4 text-sm text-muted-foreground">You skipped this case. Nothing was sent.</p>}
        {holding && !canDecide && d.status !== "sent" && d.status !== "skipped" && (
          <div role="status" className="mt-4 flex items-center gap-2 rounded-lg bg-money-dim p-4 text-sm"><CircleCheck className="size-4 text-money" aria-hidden />Approved. Preparing your packet…</div>
        )}
        {d.status === "sent" && (
          <div className="mt-4 space-y-4 border-t border-border pt-4">
            <PacketPanel runId={runId} d={d} reveal={!!holding} />
            <OutcomeForm runId={runId} d={d} onSaved={onMemoryChanged} />
          </div>
        )}
        {next && (
          <div className="mt-4 flex items-center justify-between gap-3 border-t border-border pt-4">
            <p className="text-sm text-muted-foreground">Another case is waiting for your decision.</p>
            <Button variant="outline" onClick={next.onNext}>Next case <span className="font-mono">{next.orderId}</span><ArrowRight className="size-4" aria-hidden /></Button>
          </div>
        )}
      </section>
      {d.draft && canDecide && (
        <div className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-2 rounded-xl bg-popover/95 p-3 backdrop-blur hairline" role="group" aria-label="Your decision">
          <AnimatePresence>{errors.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="w-full">
              <Alert variant="destructive"><AlertDescription>Not approved. {errors.join(" · ")}. Edit the text and try again.</AlertDescription></Alert>
            </motion.div>)}
          </AnimatePresence>
          <Button disabled={busy} onClick={() => act(editing && changed ? "edit" : "approve")}><Check className="size-4" />{editing && changed ? "Approve edited draft" : "Approve"}</Button>
          <Button variant="outline" disabled={busy} onClick={() => setEditing((v) => !v)}><Pencil className="size-4" />{editing ? "Stop editing" : "Edit"}</Button>
          <Button variant="ghost" disabled={busy} onClick={() => act("skip")}><SkipForward className="size-4" />Skip</Button>
          <p className="w-full text-xs text-muted-foreground sm:ml-auto sm:w-auto">Approving prepares a packet for you to file. Nothing leaves this app.</p>
        </div>
      )}
    </motion.article>
  );
}

function MemoryReason({ m }: { m: NonNullable<Detail["memory"]> }) {
  const moved = m.adjusted_pct !== m.base_pct;
  return (
    <div className="mt-4 rounded-lg bg-money-dim p-3">
      <p className="flex items-center gap-2 text-sm font-medium text-money"><Brain className="size-4" aria-hidden />From memory</p>
      <p className="mt-1 text-sm">
        {moved
          ? <>Starting win rate {m.adjusted_pct > m.base_pct ? "raised" : "lowered"} from {m.base_pct}% to {m.adjusted_pct}% because {m.won} of {m.total} past “{m.claim}” disputes won ({m.scope}).</>
          : <>Starting win rate stays at {m.base_pct}%: {m.won} of {m.total} past “{m.claim}” disputes won ({m.scope}).</>}
      </p>
      {m.lessons.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
          {m.lessons.map((l, i) => <li key={i}><span className="text-foreground">Lesson in memory:</span> {l}</li>)}
        </ul>
      )}
    </div>
  );
}

function Replanned({ d }: { d: Detail }) {
  const why = d.evidence.find((e) => e.supports <= 0)?.summary ?? d.skip_reason ?? "The evidence for this case is too thin.";
  return (
    <div role="status" className="rounded-lg border border-caution/40 bg-caution/10 p-3">
      <p className="flex items-center gap-2 text-sm font-medium text-caution"><GitBranch className="size-4" aria-hidden />Re-planned: moved down the queue</p>
      <p className="mt-1 text-sm">{why} Win probability is now {d.win_probability_pct}%. The agent promoted the next case and added a to-do to request the missing artifact.</p>
    </div>
  );
}
