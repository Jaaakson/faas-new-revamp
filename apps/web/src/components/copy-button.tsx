"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * Copy to clipboard with a 2s confirmation.
 *
 * The confirmation is announced through a live region as well as shown, because
 * a checkmark swap is invisible to a screen reader — and copying a code sample
 * is exactly the action a developer needs confirmed.
 */
export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="bg-background/80 size-7 backdrop-blur"
        aria-label={copied ? "Copied" : label}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
          } catch {
            // Clipboard access can be denied (insecure origin, permission).
            // Failing silently is correct here: the code is still selectable.
          }
        }}
      >
        {copied ? <Check className="text-success" /> : <Copy />}
      </Button>
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? "Copied to clipboard" : ""}
      </span>
    </>
  );
}
