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

  const refresh = useCallback(async () => {
    const id = idRef.current;
    if (!id) return;
    try {
      const [s, c] = await Promise.all([api.run(id), api.cases(id)]);
      if (idRef.current !== id) return;
      setState(s); setCases(c.cases); setHero(c.hero);
    } catch { /* the stream shows transport trouble; keep last good data */ }
  }, []);

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

  const reset = useCallback(() => {
    idRef.current = null; setRunId(null); setState(null); setEvents([]); setCases([]); setHero(null); setStartError(null);
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
    return () => { es.close(); if (timer.current) clearTimeout(timer.current); };
  }, [runId, schedule, refresh]);

  const decide = useCallback(async (caseId: string, d: "approve" | "edit" | "skip", body?: string) => {
    if (!runId) return;
    await api.decide(runId, caseId, d, body);
    schedule();
  }, [runId, schedule]);

  return { runId, state, events, cases, hero, startError, start, reset, decide, refresh };
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
