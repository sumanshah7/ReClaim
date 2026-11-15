"use client";

import { useState } from "react";
import { CircleCheck, Copy, ExternalLink } from "lucide-react";
import { api, type CaseDetail as Detail } from "@/lib/api";
import { deadlineLabel, platformLabel } from "@/lib/format";

// Reclaim cannot file for the owner: the platforms have no public dispute API. These are the owner's own portals.
const PORTAL: Record<string, { name: string; url: string }> = {
  doordash: { name: "DoorDash merchant portal", url: "https://merchants.doordash.com" },
  ubereats: { name: "Uber Eats Manager", url: "https://merchants.ubereats.com" },
};

async function copy(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

/** What "approved" means: a packet is ready, and the owner files it. Shows the next step instead of a bare "Sent". */
export function PacketPanel({ runId, d }: { runId: string; d: Detail }) {
  const [msg, setMsg] = useState("");
  const portal = PORTAL[d.platform];
  const say = (m: string) => { setMsg(m); setTimeout(() => setMsg(""), 2500); };
  const copyText = async (what: "dispute" | "packet") => {
    let text = d.draft ?? "";
    if (what === "packet") {
      try { text = (await api.file(runId, `${d.case_id.replace(/[:/]/g, "_")}/packet.md`)).text; } catch { say("Could not read the packet."); return; }
    }
    say((await copy(text)) ? "Copied." : "Copy blocked by the browser. Select the draft text instead.");
  };
  const btn = "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs transition-colors hairline hover:text-foreground text-muted-foreground";
  return (
    <div className="rounded-lg bg-money-dim p-4">
      <p className="flex items-center gap-2 text-sm font-medium"><CircleCheck className="size-4 text-money" aria-hidden />Approved. Packet ready to file.</p>
      <p className="mt-2 text-sm text-muted-foreground">
        {platformLabel(d.platform)} has no way for Reclaim to submit this for you, so the last step is yours: open the portal,
        find order <span className="font-mono text-foreground">{d.order_id}</span>, and paste the dispute text.
        File by <span className="text-foreground">{d.deadline}</span> ({deadlineLabel(d.days_left)}).
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {portal && <a href={portal.url} target="_blank" rel="noreferrer" className={btn}><ExternalLink className="size-3.5" aria-hidden />Open {portal.name}</a>}
        <button onClick={() => copyText("dispute")} className={btn}><Copy className="size-3.5" aria-hidden />Copy dispute text</button>
        <button onClick={() => copyText("packet")} className={btn}><Copy className="size-3.5" aria-hidden />Copy full packet</button>
        <span role="status" className="text-xs text-muted-foreground">{msg}</span>
      </div>
    </div>
  );
}
