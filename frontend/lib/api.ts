export type Evidence = { id: string; kind: string; supports: number; summary: string; source: string };

export type CaseRow = {
  case_id: string; platform: string; order_id: string; amount: string; amount_cents: number;
  expected_recovery: string; expected_cents: number; reason: string; claimed_item: string | null;
  win_probability_pct: number; p_win_bp: number; confidence: number; deadline: string; days_left: number;
  weak: boolean; recommend_skip: boolean; skip_reason: string | null; status: string; reasons: string[];
  evidence: Evidence[]; rank: number;
};

export type CaseDetail = CaseRow & {
  draft: string | null; cited_evidence_ids: string[];
  ticket: { order_id: string; items: string[]; image_url: string } | null;
};

export type PhoneMsg = { direction: "in" | "out"; text: string; at: string; note: string };
export type PhoneState = { mode: string; owner: string; pending: [string, string] | null; messages: PhoneMsg[] };

export type Sample = { file: string; label: string; platform: string; note: string };

export type Hero = {
  recoverable_cents: number; gross_cents: number; workable_cases: number;
  next_deadline: string | null; next_deadline_days: number | null;
};

// Event payloads differ per event type and are produced by our own backend; the UI reads only known keys.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AgentEvent = { id: number; ts: string; type: string; payload: Record<string, any> };
export type RunState = { run_id: string; status: "running" | "waiting_approval" | "done" | "error"; pending_case: string | null; hero: Hero };

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = res.statusText;
    try { const b = await res.json(); msg = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail ?? b); } catch {}
    throw new Error(msg);
  }
  return res.json();
}

export const api = {
  fixtures: () => fetch("/api/fixtures").then(j<Sample[]>),
  upload: (file: File) => { const f = new FormData(); f.append("file", file); return fetch("/api/uploads", { method: "POST", body: f }).then(j<{ upload_id: string }>); },
  start: (body: { fixture?: string; upload_id?: string }) =>
    fetch("/api/runs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }).then(j<{ run_id: string }>),
  run: (id: string) => fetch(`/api/runs/${id}`).then(j<RunState>),
  cases: (id: string) => fetch(`/api/runs/${id}/cases`).then(j<{ hero: Hero; cases: CaseRow[] }>),
  detail: (id: string, caseId: string) => fetch(`/api/runs/${id}/cases/${encodeURIComponent(caseId)}`).then(j<CaseDetail>),
  decide: (id: string, caseId: string, decision: "approve" | "edit" | "skip", body?: string) =>
    fetch(`/api/runs/${id}/cases/${encodeURIComponent(caseId)}/decision`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ decision, body }) }).then(j<{ ok: boolean }>),
  outcome: (id: string, caseId: string, o: { result: "won" | "lost"; recovered_cents: number; lesson: string }) =>
    fetch(`/api/runs/${id}/cases/${encodeURIComponent(caseId)}/outcome`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(o) }).then(j<{ ok: boolean }>),
  health: () => fetch("/api/health").then(j<{ ok: boolean; llm_mode: string; tracing?: { enabled: boolean; project: string; note: string | null; url?: string | null } }>),
  files: (id: string) => fetch(`/api/runs/${id}/files`).then(j<{ path: string; bytes: number }[]>),
  file: (id: string, path: string) => fetch(`/api/runs/${id}/files/${path.split("/").map(encodeURIComponent).join("/")}`).then(j<{ path: string; text: string }>),
  phone: () => fetch("/api/photon").then(j<PhoneState>),
  phoneSend: (sender: string, text: string) =>
    fetch("/api/photon/inbound", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sender, text }) }).then(j<{ reply: string | null }>),
  memory: () => fetch("/api/memory").then(j<{ outcomes: number; pending?: number; lessons: string }>),
};
