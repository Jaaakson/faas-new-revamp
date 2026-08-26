"use client";

import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateSubject } from "@/features/biometrics/api";

/**
 * Creating a subject is deliberately separate from enrolling one.
 *
 * A subject can exist with no biometrics — that is what `pending` means, and it
 * is how an integration registers people ahead of the day they actually show up
 * to be captured. Folding creation and enrollment into one step would make that
 * state unrepresentable, and it is the common one.
 */
export function CreateSubjectDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (subjectId: string) => void;
}) {
  const create = useCreateSubject();
  const [externalId, setExternalId] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [consent, setConsent] = React.useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const subject = await create.mutateAsync({
        external_id: externalId.trim(),
        display_name: displayName.trim() || null,
        consent_reference: consent.trim() || null,
      });
      toast.success("Subject created", {
        description: `${subject.external_id} is pending until a face is enrolled.`,
      });
      setExternalId("");
      setDisplayName("");
      setConsent("");
      onOpenChange(false);
      onCreated?.(subject.id);
    } catch (cause) {
      // A 409 on a duplicate external ID is the common case here, and the
      // server's message already names the offending value.
      toast.error("Could not create subject", {
        description: cause instanceof Error ? cause.message : undefined,
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>New subject</DialogTitle>
            <DialogDescription>
              One of your end users. They stay pending until a face is enrolled.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="external-id">External ID</Label>
              <Input
                id="external-id"
                value={externalId}
                onChange={(event) => setExternalId(event.target.value)}
                placeholder="user_84213"
                required
                maxLength={128}
                autoComplete="off"
              />
              <p className="text-muted-foreground text-xs">
                Your identifier for this person, so nothing in your database has to change.
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="display-name">Display name (optional)</Label>
              <Input
                id="display-name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                maxLength={120}
                autoComplete="off"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="consent-reference">Consent reference (optional)</Label>
              <Input
                id="consent-reference"
                value={consent}
                onChange={(event) => setConsent(event.target.value)}
                placeholder="consent_2026_07_30_84213"
                maxLength={128}
                autoComplete="off"
              />
              <p className="text-muted-foreground text-xs">
                Your own proof-of-consent record. You are the data controller; Fvas is the
                processor.
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending || !externalId.trim()}>
              {create.isPending ? "Creating…" : "Create subject"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
