import { useEffect, type RefObject } from "react";

/** Close a popover on Escape and hand focus back to the button that opened it. */
export function useEscape(open: boolean, close: () => void, returnFocusTo: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      close();
      returnFocusTo.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close, returnFocusTo]);
}
