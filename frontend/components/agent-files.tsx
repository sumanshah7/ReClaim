"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FolderOpen } from "lucide-react";
import { api } from "@/lib/api";
import { useEscape } from "@/hooks/use-escape";

type F = { path: string; bytes: number };

/** Which part of the agent (or of our safety design) produced a file. Shown so the Deep Agents pieces are visible. */
function role(path: string): { label: string; tone: string } {
  const name = path.split("/").pop() ?? path;
  if (name === "plan.md") return { label: "orchestrator's plan notes", tone: "file system" };
  if (name.endsWith("-evidence.md")) return { label: "evidence subagent's note", tone: "file system + subagent" };
  if (name === "draft.md") return { label: "dispute-writer's draft", tone: "subagent" };
  if (name === "decision.json") return { label: "the owner's decision", tone: "approval gate" };
  if (name === "sent.json" || name === "packet.md") return { label: "the filing packet", tone: "approval gate" };
  if (name === "case.json" || name === "evidence.json") return { label: "case record and evidence", tone: "deterministic code" };
  if (name === "trace.jsonl") return { label: "local audit trail of tool calls", tone: "traceability" };
  return { label: "", tone: "" };
}

export function AgentFiles({ runId, refreshKey }: { runId: string; refreshKey: number }) {
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<F[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [text, setText] = useState("");
  const btn = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useEscape(open, close, btn);

  useEffect(() => {
    if (!open) return;
    let live = true;
    api.files(runId).then((f) => live && setFiles(f)).catch(() => live && setFiles([]));
    return () => { live = false; };
  }, [open, runId, refreshKey]);

  useEffect(() => {
    if (!open || !sel) return;
    let live = true;
    api.file(runId, sel).then((x) => live && setText(x.text)).catch(() => live && setText("Could not read this file."));
    return () => { live = false; };
  }, [open, sel, runId, refreshKey]);

  const r = sel ? role(sel) : null;
  return (
    <div className="relative">
      <button ref={btn} onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hairline hover:text-foreground">
        <FolderOpen className="size-3.5" aria-hidden />Agent files
      </button>
      {open && (
        <div role="dialog" aria-label="Files the agent wrote" className="absolute right-0 top-full z-20 mt-2 w-[min(46rem,94vw)] rounded-xl bg-popover p-4 hairline">
          <p className="eyebrow">What the agent wrote to its file system</p>
          <p className="mb-3 mt-1 text-xs text-muted-foreground">One folder per case. The agent can only write plan and note files; it cannot delete or overwrite anything else.</p>
          <div className="grid gap-3 md:grid-cols-[15rem_minmax(0,1fr)]">
            <ul tabIndex={0} aria-label="Files" className="scroll-quiet max-h-80 space-y-0.5 overflow-y-auto focus-visible:outline-2 focus-visible:outline-ring">
              {files.length === 0 && <li className="text-sm text-muted-foreground">Nothing written yet.</li>}
              {files.map((f) => (
                <li key={f.path}>
                  <button onClick={() => setSel(f.path)} aria-pressed={sel === f.path}
                    className={`w-full truncate rounded px-2 py-1 text-left font-mono text-[11px] hover:text-foreground ${sel === f.path ? "bg-muted text-foreground" : "text-muted-foreground"}`}>{f.path}</button>
                </li>
              ))}
            </ul>
            <div className="min-w-0">
              {!sel ? <p className="text-sm text-muted-foreground">Pick a file to read it.</p> : (
                <>
                  {r?.label && <p className="mb-1 text-xs text-muted-foreground">{r.label} · <span className="text-foreground">{r.tone}</span></p>}
                  <pre tabIndex={0} aria-label={`Contents of ${sel}`} className="scroll-quiet max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-background p-3 font-mono text-[11px] leading-relaxed focus-visible:outline-2 focus-visible:outline-ring">{text}</pre>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
