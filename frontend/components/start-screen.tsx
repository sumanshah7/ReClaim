"use client";

import { useEffect, useRef, useState } from "react";
import { FileSpreadsheet, ShieldCheck, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { platformLabel } from "@/lib/format";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function StartScreen({ onStart, error }: { onStart: (b: { fixture?: string; file?: File }) => void; error: string | null }) {
  const [fixtures, setFixtures] = useState<string[] | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { api.fixtures().then(setFixtures).catch(() => setFixtures([])); }, []);

  const pick = (f?: File | null) => { if (f) onStart({ file: f }); };
  const nameOf = (f: string) => platformLabel(f.startsWith("uber") ? "ubereats" : "doordash");

  return (
    <div className="mx-auto grid max-w-5xl gap-10 py-10 lg:grid-cols-[1.1fr_1fr] lg:items-center lg:py-20">
      <div>
        <p className="eyebrow">For independent restaurants</p>
        <h1 className="mt-3 text-4xl font-semibold leading-[1.05] tracking-tight md:text-6xl">
          Get back what the platforms <span className="text-money">took</span>.
        </h1>
        <p className="mt-5 max-w-md text-base text-muted-foreground">
          Drop in a payout report. Reclaim finds refund deductions, gathers evidence from your order tickets, and drafts a factual dispute.
          You approve every one. Nothing is sent without you.
        </p>
        <p className="mt-6 flex items-center gap-2 text-sm text-muted-foreground"><ShieldCheck className="size-4 text-money" aria-hidden />Customer names are hashed on this machine. Only case facts go to the model.</p>
      </div>

      <div className="space-y-3">
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}
          className={cn("flex flex-col items-center gap-3 rounded-xl border border-dashed border-border bg-card px-6 py-10 text-center transition-colors", drag && "border-money bg-money-dim")}
        >
          <Upload className="size-6 text-muted-foreground" aria-hidden />
          <div>
            <p className="font-medium">Drop a payout CSV</p>
            <p className="mt-1 text-xs text-muted-foreground">DoorDash or Uber Eats. Screenshot and PDF reports are planned.</p>
          </div>
          <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" aria-label="Choose a payout CSV" onChange={(e) => pick(e.target.files?.[0])} />
          <Button variant="outline" onClick={() => input.current?.click()}>Choose file</Button>
        </div>

        <div className="rounded-xl bg-card p-4 hairline">
          <p className="eyebrow mb-3">Or try a sample</p>
          {fixtures === null ? (
            <p className="text-sm text-muted-foreground">Loading samples…</p>
          ) : fixtures.length === 0 ? (
            <p className="text-sm text-muted-foreground">No samples found. Is the backend running on port 8000?</p>
          ) : (
            <ul className="space-y-2">
              {fixtures.map((f) => (
                <li key={f}>
                  <Button variant="secondary" className="w-full justify-start gap-3" onClick={() => onStart({ fixture: f })}>
                    <FileSpreadsheet className="size-4" aria-hidden />{nameOf(f)} payout <span className="ml-auto font-mono text-xs text-muted-foreground">synthetic</span>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      </div>
    </div>
  );
}
