"use client";

import Image from "next/image";
import { useEffect, useMemo, useState } from "react";
import { MotionConfig } from "motion/react";
import { Activity, FlaskConical, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { useCaseDetail, useRun } from "@/hooks/use-run";
import { AgentPanel } from "@/components/agent-panel";
import { CaseDetail } from "@/components/case-detail";
import { CaseQueue } from "@/components/case-queue";
import { ErrorState } from "@/components/error-state";
import { Hero } from "@/components/hero";
import { MemoryStrip } from "@/components/memory-strip";
import { PhoneSim } from "@/components/phone-sim";
import { AgentFiles } from "@/components/agent-files";
import { StartScreen } from "@/components/start-screen";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export default function Page() {
  const run = useRun();
  const [picked, setPicked] = useState<string | null>(null);
  const [memKey, setMemKey] = useState(0);
  const pending = run.state?.pending_case ?? null;
  const [mode, setMode] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ enabled: boolean; project: string; url?: string | null } | null>(null);
  useEffect(() => { api.health().then((h) => { setMode(h.llm_mode); setTrace(h.tracing ?? null); }).catch(() => setMode(null)); }, []);

  // Selection is derived: bring the owner to whatever newly needs a decision (and reset for a new run),
  // otherwise keep their pick, otherwise show the top case.
  const [seen, setSeen] = useState<{ run: string | null; pending: string | null }>({ run: null, pending: null });
  if (seen.run !== run.runId || seen.pending !== pending) {
    setSeen({ run: run.runId, pending });
    setPicked(seen.run !== run.runId ? null : pending ?? picked);
  }
  const selected = picked ?? run.cases[0]?.case_id ?? null;
  const setSelected = setPicked;

  const cur = run.cases.find((c) => c.case_id === selected);
  const version = `${cur?.status}|${cur?.evidence.length}|${cur?.p_win_bp}`;
  const { detail, loading } = useCaseDetail(run.runId, selected, version);
  const errEvent = useMemo(() => [...run.events].reverse().find((e) => e.type === "error" && e.payload.kind !== "code_changed"), [run.events]);   // a code change is handled by switching to the fresh run

  return (
    <MotionConfig reducedMotion="user">
      <div className="mx-auto flex min-h-dvh max-w-[1500px] flex-col gap-6 px-4 py-5 md:px-8">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-baseline gap-3">
            <span className="inline-flex items-center rounded-lg bg-white px-2.5 py-1.5"><Image src="/reclaim-logo.png" alt="Reclaim" width={1862} height={309} priority unoptimized className="h-8 w-auto sm:h-9" /></span>
            <span className="hidden font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground sm:inline">you approve every dispute</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {mode === "scripted" && <span title="A deterministic test model is driving the agent, not Claude." className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-wider text-caution hairline"><FlaskConical className="size-3.5" />Scripted dev model</span>}
            {trace?.enabled && (trace.url ? <a href={trace.url} target="_blank" rel="noreferrer" title="Open this project in LangSmith (opens a new tab)." className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hairline hover:text-foreground"><Activity className="size-3.5" />Traced · {trace.project} ↗</a> : <span title={`Each run is traced to LangSmith project “${trace.project}”.`} className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground hairline"><Activity className="size-3.5" />Traced · {trace.project}</span>)}
            <MemoryStrip refreshKey={memKey + (run.state?.status === "done" ? 1 : 0)} />
            {run.runId && <AgentFiles runId={run.runId} refreshKey={run.events.length} />}
            <PhoneSim />
            {run.runId && <Button variant="ghost" size="sm" onClick={run.reset}><RotateCcw className="size-3.5" />New report</Button>}
          </div>
        </header>

        {!run.runId ? (
          <StartScreen onStart={run.start} error={run.startError} />
        ) : errEvent ? (
          <ErrorState kind={errEvent.payload.kind} message={String(errEvent.payload.message)} onReset={run.reset} />
        ) : (
          <>
            <Hero hero={run.hero} loading={run.cases.length === 0} />
            <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[340px_minmax(0,1fr)] xl:grid-cols-[340px_minmax(0,1fr)_340px]">
              <h1 className="sr-only">Reclaim case queue</h1>
              {run.cases.length === 0 ? (
                <div className="space-y-2" aria-label="Loading cases">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24 w-full" />)}</div>
              ) : (
                <div className="lg:max-h-[calc(100dvh-14rem)] lg:overflow-hidden flex flex-col">
                  <CaseQueue cases={run.cases} selected={selected} pendingCase={pending} onSelect={setSelected} />
                </div>
              )}
              <div className="min-w-0 lg:max-h-[calc(100dvh-14rem)] lg:overflow-y-auto scroll-quiet lg:pr-1">
                <CaseDetail
                  runId={run.runId} detail={detail} loading={loading}
                  canDecide={!!detail && detail.case_id === pending && run.state?.status === "waiting_approval"}
                  onDecide={(d, body) => run.decide(detail!.case_id, d, body)}
                  onMemoryChanged={() => setMemKey((k) => k + 1)}
                />
              </div>
              <div className="lg:col-span-2 xl:col-span-1 xl:max-h-[calc(100dvh-14rem)] flex flex-col min-h-72">
                <AgentPanel events={run.events} state={run.state} />
              </div>
            </main>
          </>
        )}
      </div>
    </MotionConfig>
  );
}
