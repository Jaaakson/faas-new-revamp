"use client";

import * as React from "react";
import { KeyRound, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { PageHeader } from "@/components/console/page-header";
import { RevealKeyDialog } from "@/components/console/reveal-key-dialog";
import { EmptyState, ErrorState } from "@/components/console/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import { Skeleton } from "@/components/ui/skeleton";
import {
  type ApiKey,
  type ApiKeyCreated,
  SCOPES,
  useApiKeys,
  useCreateApiKey,
  useRevokeApiKey,
  useRotateApiKey,
} from "@/features/api-keys/api";
import { absoluteTime, relativeTime } from "@/lib/format";

const STATUS_VARIANT: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  active: "success",
  rotating: "warning",
  revoked: "destructive",
  expired: "secondary",
  rotation_overlap_elapsed: "secondary",
};

export default function ApiKeysPage() {
  const query = useApiKeys();
  const create = useCreateApiKey();
  const rotate = useRotateApiKey();
  const revoke = useRevokeApiKey();

  const [creating, setCreating] = React.useState(false);
  const [revealed, setRevealed] = React.useState<ApiKeyCreated | null>(null);
  const [confirmRevoke, setConfirmRevoke] = React.useState<ApiKey | null>(null);

  const keys = query.data ?? [];

  const handleRotate = async (key: ApiKey) => {
    try {
      setRevealed(await rotate.mutateAsync(key.id));
      toast.success("Key rotated", {
        description: "The old key keeps working for 24 hours so you can redeploy.",
      });
    } catch (cause) {
      toast.error("Could not rotate the key", {
        description: cause instanceof Error ? cause.message : undefined,
      });
    }
  };

  const handleRevoke = async () => {
    if (!confirmRevoke) return;
    try {
      await revoke.mutateAsync(confirmRevoke.id);
      toast.success("Key revoked", { description: "It stops working on the next request." });
    } catch (cause) {
      toast.error("Could not revoke the key", {
        description: cause instanceof Error ? cause.message : undefined,
      });
    } finally {
      setConfirmRevoke(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="API keys"
        description="How your backend authenticates. Keys reach biometric operations only — never settings, members, or billing."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" aria-hidden />
            New key
          </Button>
        }
      />

      <Card className="overflow-hidden">
        {query.isError ? (
          <div className="p-5">
            <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          </div>
        ) : query.isLoading ? (
          <div className="divide-y">
            {Array.from({ length: 3 }, (_, index) => (
              <div key={index} className="flex items-center gap-4 px-5 py-3">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-4 w-48" />
                <Skeleton className="ml-auto h-5 w-16 rounded-full" />
              </div>
            ))}
          </div>
        ) : keys.length === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={KeyRound}
              title="No API keys yet"
              description="Create a test key to try the API from your terminal, then a live key when you go to production."
              docsHref="/docs/authentication"
              action={
                <Button size="sm" onClick={() => setCreating(true)}>
                  <Plus className="size-3.5" aria-hidden />
                  New key
                </Button>
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">API keys</caption>
              <thead>
                <tr className="text-muted-foreground border-b text-left text-xs">
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Name
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Key
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Env
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Status
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Last used
                  </th>
                  <th scope="col" className="px-5 py-2.5 text-right font-medium">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {keys.map((key) => (
                  <tr key={key.id} className="hover:bg-accent/40">
                    <td className="px-5 py-2.5">
                      <div className="font-medium">{key.name}</div>
                      <div className="text-muted-foreground font-mono text-[11px]">
                        {key.scopes.length} scope{key.scopes.length === 1 ? "" : "s"}
                      </div>
                    </td>
                    <td className="px-5 py-2.5 font-mono text-xs">
                      {key.key_prefix}
                      <span className="text-muted-foreground">…{key.last4}</span>
                    </td>
                    <td className="px-5 py-2.5">
                      <Badge variant={key.environment === "live" ? "info" : "outline"}>
                        {key.environment}
                      </Badge>
                    </td>
                    <td className="px-5 py-2.5">
                      <Badge variant={STATUS_VARIANT[key.status] ?? "outline"}>
                        {key.status.replace(/_/g, " ")}
                      </Badge>
                    </td>
                    <td className="text-muted-foreground px-5 py-2.5 text-xs whitespace-nowrap">
                      {key.last_used_at ? (
                        <time dateTime={key.last_used_at} title={absoluteTime(key.last_used_at)}>
                          {relativeTime(key.last_used_at)}
                        </time>
                      ) : (
                        "Never"
                      )}
                    </td>
                    <td className="px-5 py-2.5 text-right whitespace-nowrap">
                      {key.revoked_at ? (
                        <span className="text-muted-foreground text-xs">—</span>
                      ) : (
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void handleRotate(key)}
                            disabled={rotate.isPending}
                          >
                            <RefreshCw className="size-3.5" aria-hidden />
                            Rotate
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setConfirmRevoke(key)}>
                            <Trash2 className="size-3.5" aria-hidden />
                            Revoke
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <CreateKeyDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(key) => setRevealed(key)}
        pending={create.isPending}
        submit={create.mutateAsync}
      />

      <RevealKeyDialog created={revealed} onClose={() => setRevealed(null)} />

      <Dialog
        open={confirmRevoke !== null}
        onOpenChange={(open) => !open && setConfirmRevoke(null)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Revoke “{confirmRevoke?.name}”?</DialogTitle>
            <DialogDescription>
              It stops working on the very next request — there is no grace period. Anything still
              using it will start returning <code className="text-[11px]">401</code>.
              <br />
              <br />
              If you are replacing it as part of a planned deploy, use <strong>Rotate</strong>{" "}
              instead: that keeps the old key alive for 24 hours.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmRevoke(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={revoke.isPending}
              onClick={() => void handleRevoke()}
            >
              Revoke now
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function CreateKeyDialog({
  open,
  onOpenChange,
  onCreated,
  pending,
  submit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (key: ApiKeyCreated) => void;
  pending: boolean;
  submit: (input: {
    name: string;
    environment: string;
    scopes?: string[];
  }) => Promise<ApiKeyCreated>;
}) {
  const [name, setName] = React.useState("");
  const [environment, setEnvironment] = React.useState("test");
  const [scopes, setScopes] = React.useState<string[]>([
    "subject:read",
    "subject:write",
    "enrollment:write",
    "verification:write",
    "verification:read",
  ]);

  const toggle = (value: string) => {
    setScopes((current) =>
      current.includes(value) ? current.filter((s) => s !== value) : [...current, value],
    );
  };

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const created = await submit({ name: name.trim(), environment, scopes });
      setName("");
      onOpenChange(false);
      onCreated(created);
    } catch (cause) {
      toast.error("Could not create the key", {
        description: cause instanceof Error ? cause.message : undefined,
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={onSubmit}>
          <DialogHeader>
            <DialogTitle>New API key</DialogTitle>
            <DialogDescription>
              Grant only the scopes this integration needs. A key can never exceed your own role,
              and never reaches the console.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="key-name">Name</Label>
              <Input
                id="key-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Production backend"
                required
                maxLength={100}
                autoComplete="off"
              />
            </div>

            <fieldset className="space-y-1.5">
              <legend className="text-sm font-medium">Environment</legend>
              <div className="flex gap-2">
                {["test", "live"].map((value) => (
                  <label
                    key={value}
                    className={`flex flex-1 cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                      environment === value ? "border-primary bg-primary/5" : ""
                    }`}
                  >
                    <input
                      type="radio"
                      name="environment"
                      value={value}
                      checked={environment === value}
                      onChange={() => setEnvironment(value)}
                      className="sr-only"
                    />
                    <span className="font-medium">{value}</span>
                    <span className="text-muted-foreground text-xs">
                      {value === "test" ? "Free, unlimited" : "Counts against your plan"}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Scopes</legend>
              <div className="space-y-1.5">
                {SCOPES.map((scope) => (
                  <label
                    key={scope.value}
                    className="hover:bg-accent/40 flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5"
                  >
                    <input
                      type="checkbox"
                      checked={scopes.includes(scope.value)}
                      onChange={() => toggle(scope.value)}
                      className="mt-0.5"
                    />
                    <span className="min-w-0">
                      <span className="block text-sm">{scope.label}</span>
                      <span className="text-muted-foreground block text-xs">{scope.detail}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending || !name.trim() || scopes.length === 0}>
              {pending ? "Creating…" : "Create key"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
