"use client";

import * as React from "react";
import { AlertTriangle, Check, Copy, KeyRound } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ApiKeyCreated } from "@/features/api-keys/api";
import { cn } from "@/lib/utils";

/**
 * The one and only time a secret is visible.
 *
 * **The dialog cannot be dismissed until the secret has been copied.** That is
 * not paternalism — there is genuinely no way to recover it. The digest is all
 * the server keeps, so a user who clicks away has to rotate the key and redo
 * whatever they were configuring.
 *
 * Escape, the overlay, and the close button are all disabled until then, and
 * the only enabled action is Copy. Once copied, the dialog says so and lets go.
 */
export function RevealKeyDialog({
  created,
  onClose,
}: {
  created: ApiKeyCreated | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    // A new key means a new secret to copy; never inherit the previous state.
    setCopied(false);
  }, [created?.id]);

  const copy = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.secret);
      setCopied(true);
    } catch {
      // Clipboard access can be refused (insecure context, permissions policy).
      // Select the text instead so the user can copy it by hand, and still let
      // them proceed — trapping them in a dialog they cannot satisfy is worse.
      selectSecret();
      setCopied(true);
    }
  };

  const selectSecret = () => {
    const node = document.getElementById("api-key-secret");
    if (!node) return;
    const range = document.createRange();
    range.selectNodeContents(node);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  };

  return (
    <Dialog
      open={created !== null}
      onOpenChange={(open) => {
        // Only a copied secret may close the dialog.
        if (!open && copied) onClose();
      }}
    >
      <DialogContent
        className="sm:max-w-lg"
        showClose={copied}
        onEscapeKeyDown={(event) => {
          if (!copied) event.preventDefault();
        }}
        onPointerDownOutside={(event) => {
          if (!copied) event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (!copied) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="size-4" aria-hidden />
            Copy your API key
          </DialogTitle>
          <DialogDescription>
            This is the only time it will be shown. Only a hash is stored, so it cannot be retrieved
            later — if you lose it, rotate the key.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="bg-muted flex items-start gap-2 rounded-lg border p-3">
            <code
              id="api-key-secret"
              className="min-w-0 flex-1 font-mono text-xs leading-relaxed break-all select-all"
            >
              {created?.secret}
            </code>
            <Button
              size="sm"
              variant={copied ? "outline" : "default"}
              onClick={() => void copy()}
              className="shrink-0"
            >
              {copied ? (
                <>
                  <Check className="size-3.5" aria-hidden />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="size-3.5" aria-hidden />
                  Copy
                </>
              )}
            </Button>
          </div>

          <div
            className={cn(
              "flex gap-2.5 rounded-lg border px-3 py-2.5 text-xs leading-relaxed transition-colors",
              copied
                ? "border-emerald-500/30 bg-emerald-500/5"
                : "border-amber-500/30 bg-amber-500/5",
            )}
            role="status"
            aria-live="polite"
          >
            {copied ? (
              <Check className="mt-0.5 size-4 shrink-0 text-emerald-500" aria-hidden />
            ) : (
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" aria-hidden />
            )}
            <p className="text-muted-foreground">
              {copied
                ? "Stored somewhere safe? Treat it like a password — anyone holding it can verify faces against your account."
                : "Copy the key before closing. This dialog will not let you leave until you have."}
            </p>
          </div>

          <dl className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <dt className="text-muted-foreground">Environment</dt>
              <dd className="mt-0.5 font-medium">{created?.environment}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Scopes</dt>
              <dd className="mt-0.5 font-mono text-[11px]">{created?.scopes.join(", ")}</dd>
            </div>
          </dl>
        </div>

        <div className="flex justify-end">
          <Button onClick={onClose} disabled={!copied}>
            {copied ? "Done" : "Copy the key first"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
