"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AgentEvent, type CaseDetail, type CaseRow, type Hero, type RunState } from "@/lib/api";

export function useRun() {
  const [runId, setRunId] = useState<string | null>(null);
  const [state, setState] = useState<RunState | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [hero, setHero] = useState<Hero | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const seen = useRef(new Set<number>());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idRef = useRef<string | null>(null);
  const stoppedSince = useRef<number | null>(null);

  const follow = useCallback((id: string) => {   // switch to another run (the fresh one after a backend restart)
    seen.current = new Set(); idRef.current = id; stoppedSince.current = null;
    setEvents([]); setCases([]); setHero(null); setState(null); setRunId(id);
  }, []);

  const reset = useCallback((message: string | null = null) => {
    idRef.current = null; stoppedSince.current = null;
    setRunId(null); setState(null); setEvents([]); setCases([]); setHero(null); setStartError(message);
  }, []);

  const refresh = useCallback(async () => {
    const id = idRef.current;
    if (!id) return;
    try {
      const s = await api.run(id);
      if (idRef.current !== id) return;
      if (s.status === "stopped") {   // the backend stopped this run because its code changed and is restarting
        if (s.replaced_by) { follow(s.replaced_by); return; }
        stoppedSince.current ??= Date.now();
        if (Date.now() - stoppedSince.current > 45_000) { reset("The server did not come back after a code change. Start the report again."); return; }
        setState(s); return;
      }
      stoppedSince.current = null;
      const c = await api.cases(id);
      if (idRef.current !== id) return;
      setState(s); setCases(c.cases); setHero(c.hero);
    } catch (e) {
      if ((e as { status?: number }).status === 404) { reset("The server restarted, so this run was lost. Start the report again."); return; }
      /* otherwise: transport trouble (for example the server is restarting); keep the last good data and keep polling */
    }
  }, [follow, reset]);

  const schedule = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(refresh, 120);
  }, [refresh]);

  const start = useCallback(async (body: { fixture?: string; file?: File }) => {
    setStartError(null);
    try {
      const upload_id = body.file ? (await api.upload(body.file)).upload_id : undefined;
      const { run_id } = await api.start(upload_id ? { upload_id } : { fixture: body.fixture });
      seen.current = new Set(); idRef.current = run_id;
      setEvents([]); setCases([]); setHero(null); setState(null); setRunId(run_id);
    } catch (e) {
      setStartError(e instanceof Error ? e.message : "Could not start the run.");
    }
  }, []);

  useEffect(() => {
    if (!runId) return;
    const es = new EventSource(`/api/runs/${runId}/events`);
    es.onmessage = (m) => {
      const id = Number(m.lastEventId);
      if (seen.current.has(id)) return; // EventSource replays on reconnect
      seen.current.add(id);
      setEvents((prev) => [...prev, { id, ...JSON.parse(m.data) }]);
      schedule();
    };
    es.addEventListener("end", () => { es.close(); refresh(); });
    refresh();
    // The event stream cannot survive a backend restart, so also poll until the run is finished.
    const poll = setInterval(refresh, 2000);
    return () => { es.close(); clearInterval(poll); if (timer.current) clearTimeout(timer.current); };
  }, [runId, schedule, refresh]);

  const decide = useCallback(async (caseId: string, d: "approve" | "edit" | "skip", body?: string) => {
    if (!runId) return;
    await api.decide(runId, caseId, d, body);
    schedule();
  }, [runId, schedule]);

  return { runId, state, events, cases, hero, startError, start, reset: () => reset(null), decide, refresh };
}

export function useCaseDetail(runId: string | null, caseId: string | null, version: string) {
  const key = runId && caseId ? `${runId}|${caseId}|${version}` : null;
  const [res, setRes] = useState<{ key: string; detail: CaseDetail } | null>(null);
  useEffect(() => {
    if (!key || !runId || !caseId) return;
    let live = true;
    api.detail(runId, caseId).then((detail) => live && setRes({ key, detail })).catch(() => {});
    return () => { live = false; };
  }, [key, runId, caseId]);
  // Keep showing the previous version of the same case while it refreshes (no flicker); never show another case's data.
  const detail = res && caseId && res.detail.case_id === caseId ? res.detail : null;
  return { detail, loading: !!key && res?.key !== key };
}
