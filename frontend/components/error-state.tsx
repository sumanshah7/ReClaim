import { RotateCcw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ErrorState({ kind, message, onReset }: { kind?: string; message: string; onReset: () => void }) {
  const cache = kind === "cache_miss";
  return (
    <div role="alert" className="mx-auto flex max-w-xl flex-col items-start gap-4 rounded-xl bg-card p-8 hairline">
      <span className="grid size-10 place-items-center rounded-lg bg-danger/15 text-danger"><TriangleAlert className="size-5" /></span>
      <div>
        <h2 className="text-lg font-semibold">{cache ? "This path isn't in the offline cache" : "The run stopped"}</h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          {cache
            ? "The demo replays recorded model responses, and there is no recording for this step. Nothing was sent. Record it with an API key (make record), or follow the path that was recorded."
            : "Something went wrong while the agent was working. Nothing was sent. Your cases and any approvals so far are safe."}
        </p>
        <pre className="scroll-quiet mt-3 max-h-32 overflow-auto whitespace-pre-wrap rounded-md bg-raised p-3 font-mono text-xs text-muted-foreground">{message}</pre>
      </div>
      <Button variant="outline" onClick={onReset}><RotateCcw className="size-4" />Start over</Button>
    </div>
  );
}
