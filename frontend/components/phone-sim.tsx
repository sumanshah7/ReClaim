"use client";

import { useEffect, useRef, useState } from "react";
import { MessageSquare, Send } from "lucide-react";
import { api, type PhoneState } from "@/lib/api";

/** The owner's phone, simulated. Texts go through the same approval gate as the buttons (constitution rule 1). */
export function PhoneSim() {
  const [open, setOpen] = useState(false);
  const [st, setSt] = useState<PhoneState | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    const tick = () => api.phone().then((s) => live && setSt(s)).catch(() => live && setSt(null));
    tick();
    const t = setInterval(tick, open ? 1200 : 4000);
    return () => { live = false; clearInterval(t); };
  }, [open]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [st?.messages.length, open]);

  if (!st) return null;
  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try { await api.phoneSend(st.owner, text); setDraft(""); setSt(await api.phone()); } finally { setBusy(false); }
  };
  const waiting = !!st.pending;
  return (
    <div className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="relative flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hairline hover:text-foreground">
        <MessageSquare className="size-3.5" aria-hidden />Text approval
        {waiting && <span className="size-1.5 rounded-full bg-money" aria-label="a text is waiting for your reply" />}
      </button>
      {open && (
        <div role="dialog" aria-label="Simulated owner phone" className="absolute right-0 top-full z-20 mt-2 flex w-[min(24rem,92vw)] flex-col rounded-xl bg-popover p-4 hairline">
          <p className="eyebrow">Owner&apos;s phone · {st.mode === "simulator" ? "simulator" : "live link"}</p>
          <p className="mb-3 mt-1 text-xs text-muted-foreground">Same gate as the buttons. Only a plain YES sends anything.</p>
          <div className="scroll-quiet flex max-h-72 min-h-24 flex-col gap-2 overflow-y-auto">
            {st.messages.length === 0 && <p className="text-sm text-muted-foreground">No messages yet. Start a run; the first draft arrives here.</p>}
            {st.messages.map((m, i) => (
              <div key={i} className={m.direction === "out" ? "max-w-[88%] self-start" : "max-w-[88%] self-end"}>
                <p className={`whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${m.direction === "out" ? "bg-muted text-foreground" : "bg-money text-primary-foreground"}`}>{m.text}</p>
                {m.note && <p className="mt-0.5 text-[11px] text-muted-foreground">{m.note}</p>}
              </div>
            ))}
            <div ref={end} />
          </div>
          <div className="mt-3 flex gap-2">
            {["YES", "NO"].map((q) => (
              <button key={q} disabled={busy} onClick={() => send(q)} className="rounded-full px-3 py-1 text-xs hairline hover:text-foreground disabled:opacity-50">{q}</button>
            ))}
          </div>
          <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
            <input value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Reply by text" placeholder="Reply…"
              className="min-w-0 flex-1 rounded-md bg-background px-3 py-2 text-sm hairline outline-none focus-visible:ring-2 focus-visible:ring-ring" />
            <button type="submit" disabled={busy || !draft.trim()} aria-label="Send reply" className="rounded-md px-3 hairline disabled:opacity-50"><Send className="size-4" aria-hidden /></button>
          </form>
        </div>
      )}
    </div>
  );
}
