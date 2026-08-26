"use client";

import * as React from "react";
import { AlertTriangle, Plus, RefreshCw, Send, Trash2, Webhook } from "lucide-react";
import { toast } from "sonner";

import { CopyButton } from "@/components/copy-button";
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
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  WEBHOOK_EVENTS,
  type WebhookEndpoint,
  useCreateWebhook,
  useDeleteWebhook,
  useRotateSecret,
  useTestWebhook,
  useWebhookDeliveries,
  useWebhooks,
} from "@/features/webhooks/api";
import { absoluteTime, relativeTime } from "@/lib/format";

export default function WebhooksPage() {
  const webhooks = useWebhooks();
  const [creating, setCreating] = React.useState(false);
  const [revealed, setRevealed] = React.useState<{ url: string; secret: string } | null>(null);
  const [expanded, setExpanded] = React.useState<string | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Webhooks</h2>
          <p className="text-muted-foreground mt-1 text-sm">
            Signed event delivery. Every payload carries an HMAC-SHA256 signature over{" "}
            <code className="text-xs">{"{timestamp}.{body}"}</code> — verify it, and reject anything
            older than five minutes.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="size-4" aria-hidden />
          Add endpoint
        </Button>
      </div>

      <div className="border-info/30 bg-info/5 rounded-lg border px-3.5 py-3 text-xs leading-relaxed">
        <p className="font-medium">Delivery is at-least-once.</p>
        <p className="text-muted-foreground mt-0.5">
          A retry after a timeout can deliver the same event twice, so dedupe on{" "}
          <code>Fvas-Event-Id</code>. That is normal operation, not an incident.
        </p>
      </div>

      {webhooks.isError ? (
        <ErrorState error={webhooks.error} onRetry={() => void webhooks.refetch()} />
      ) : webhooks.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (webhooks.data?.length ?? 0) === 0 ? (
        <EmptyState
          icon={Webhook}
          title="No endpoints yet"
          description="Get notified when a verification completes, an enrollment finds a duplicate, or a quota threshold is crossed."
          docsHref="/docs/webhooks"
          action={
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="size-3.5" aria-hidden />
              Add endpoint
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {webhooks.data?.map((endpoint) => (
            <EndpointCard
              key={endpoint.id}
              endpoint={endpoint}
              expanded={expanded === endpoint.id}
              onToggle={() => setExpanded(expanded === endpoint.id ? null : endpoint.id)}
              onRevealed={setRevealed}
            />
          ))}
        </div>
      )}

      <CreateDialog open={creating} onOpenChange={setCreating} onCreated={setRevealed} />
      <SecretDialog revealed={revealed} onClose={() => setRevealed(null)} />
    </div>
  );
}

function EndpointCard({
  endpoint,
  expanded,
  onToggle,
  onRevealed,
}: {
  endpoint: WebhookEndpoint;
  expanded: boolean;
  onToggle: () => void;
  onRevealed: (value: { url: string; secret: string }) => void;
}) {
  const test = useTestWebhook();
  const rotate = useRotateSecret();
  const remove = useDeleteWebhook();
  const deliveries = useWebhookDeliveries(expanded ? endpoint.id : null);

  return (
    <Card className="overflow-hidden">
      <div className="space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <code className="truncate text-sm">{endpoint.url}</code>
              {endpoint.is_active ? (
                <Badge variant="success">active</Badge>
              ) : (
                <Badge variant="destructive">disabled</Badge>
              )}
            </div>
            <div className="text-muted-foreground flex flex-wrap items-center gap-1.5 text-xs">
              <span className="font-mono">{endpoint.secret_hint}</span>
              <span aria-hidden>·</span>
              <span>
                {endpoint.last_delivery_at
                  ? `last delivered ${relativeTime(endpoint.last_delivery_at)}`
                  : "never delivered"}
              </span>
            </div>
          </div>

          <div className="flex shrink-0 gap-1.5">
            <Button
              variant="outline"
              size="sm"
              disabled={test.isPending}
              onClick={() =>
                test.mutate(endpoint.id, {
                  onSuccess: (delivery) =>
                    delivery.status === "delivered"
                      ? toast.success("Test event delivered", {
                          description: `Your endpoint returned ${delivery.response_status}.`,
                        })
                      : toast.warning("Test event could not be delivered", {
                          description: delivery.error ?? "See the delivery log below.",
                        }),
                  onError: (error) =>
                    toast.error("Could not send", {
                      description: error instanceof Error ? error.message : undefined,
                    }),
                })
              }
            >
              <Send className="size-3.5" aria-hidden />
              Test
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={rotate.isPending}
              onClick={() =>
                rotate.mutate(endpoint.id, {
                  onSuccess: (result) => onRevealed({ url: result.url, secret: result.secret }),
                })
              }
            >
              <RefreshCw className="size-3.5" aria-hidden />
              Rotate
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                remove.mutate(endpoint.id, {
                  onSuccess: () => toast.success("Endpoint removed"),
                })
              }
            >
              <Trash2 className="size-3.5" aria-hidden />
            </Button>
          </div>
        </div>

        {!endpoint.is_active ? (
          <p className="text-destructive flex items-start gap-2 text-xs">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Auto-disabled after {endpoint.failure_count} consecutive failures. Fix the endpoint,
            then re-enable it — reactivating clears the counter.
          </p>
        ) : null}

        <div className="flex flex-wrap gap-1.5">
          {endpoint.events.map((event) => (
            <Badge key={event} variant="outline">
              {event}
            </Badge>
          ))}
        </div>

        <Button variant="ghost" size="sm" className="-ml-2" onClick={onToggle}>
          {expanded ? "Hide" : "Show"} delivery log
        </Button>
      </div>

      {expanded ? (
        <div className="border-t">
          {deliveries.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : (deliveries.data?.length ?? 0) === 0 ? (
            <p className="text-muted-foreground p-4 text-center text-xs">No deliveries yet.</p>
          ) : (
            <table className="w-full text-xs">
              <caption className="sr-only">Deliveries for {endpoint.url}</caption>
              <thead>
                <tr className="text-muted-foreground border-b text-left">
                  <th scope="col" className="px-4 py-2 font-medium">
                    Event
                  </th>
                  <th scope="col" className="px-4 py-2 font-medium">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">
                    Attempts
                  </th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">
                    Response
                  </th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">
                    When
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {deliveries.data?.map((delivery) => (
                  <tr key={delivery.id}>
                    <td className="px-4 py-2">{delivery.event_type}</td>
                    <td className="px-4 py-2">
                      <Badge
                        variant={
                          delivery.status === "delivered"
                            ? "success"
                            : delivery.status === "failed"
                              ? "destructive"
                              : "warning"
                        }
                      >
                        {delivery.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{delivery.attempt_count}</td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {delivery.response_status ?? (delivery.error ? "—" : "")}
                    </td>
                    <td
                      className="text-muted-foreground px-4 py-2 text-right whitespace-nowrap"
                      title={absoluteTime(delivery.created_at)}
                    >
                      {relativeTime(delivery.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : null}
    </Card>
  );
}

function CreateDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (value: { url: string; secret: string }) => void;
}) {
  const create = useCreateWebhook();
  const [url, setUrl] = React.useState("");
  const [events, setEvents] = React.useState<string[]>(["verification.completed"]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    create.mutate(
      { url: url.trim(), events },
      {
        onSuccess: (result) => {
          setUrl("");
          onOpenChange(false);
          onCreated({ url: result.url, secret: result.secret });
        },
        onError: (error) =>
          toast.error("Could not create endpoint", {
            description: error instanceof Error ? error.message : undefined,
          }),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Add a webhook endpoint</DialogTitle>
            <DialogDescription>
              https only, and it must resolve to a public host — loopback and link-local addresses
              are refused.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="webhook-url">Endpoint URL</Label>
              <Input
                id="webhook-url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://api.yourcompany.com/webhooks/fvas"
                required
                autoComplete="off"
              />
            </div>

            <fieldset className="space-y-1.5">
              <legend className="text-sm font-medium">Events</legend>
              <div className="space-y-1.5 pt-1">
                {WEBHOOK_EVENTS.map((event) => (
                  <label key={event} className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={events.includes(event)}
                      onChange={(changed) =>
                        setEvents((previous) =>
                          changed.target.checked
                            ? [...previous, event]
                            : previous.filter((value) => value !== event),
                        )
                      }
                      className="size-3.5"
                    />
                    <code>{event}</code>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending || !url.trim() || !events.length}>
              {create.isPending ? "Creating…" : "Create endpoint"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The reveal-once dialog.
 *
 * Deliberately hard to dismiss by accident: the secret cannot be retrieved
 * afterwards, and a customer who closes this without copying has to rotate and
 * redeploy.
 */
function SecretDialog({
  revealed,
  onClose,
}: {
  revealed: { url: string; secret: string } | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    if (revealed) setCopied(false);
  }, [revealed]);

  return (
    <Dialog open={revealed !== null} onOpenChange={(open) => !open && copied && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Copy your signing secret</DialogTitle>
          <DialogDescription>
            This is the only time it is shown. It cannot be retrieved later — if you lose it, you
            will have to rotate and redeploy.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <p className="text-muted-foreground truncate text-xs">{revealed?.url}</p>
          <div className="bg-muted flex items-center gap-2 rounded-md border p-2.5">
            <code className="min-w-0 flex-1 truncate text-xs">{revealed?.secret}</code>
            <span onClick={() => setCopied(true)}>
              <CopyButton value={revealed?.secret ?? ""} />
            </span>
          </div>

          <Separator />

          <div className="text-muted-foreground space-y-1.5 text-xs leading-relaxed">
            <p className="font-medium">Verifying a delivery</p>
            <p>
              Compute{" "}
              <code>
                HMAC-SHA256(secret, `${"{t}"}.${"{raw body}"}`)
              </code>{" "}
              and compare it in constant time with the <code>v1</code> value in{" "}
              <code>Fvas-Signature</code>. Reject anything where <code>t</code> is more than five
              minutes old — that is what stops a captured request being replayed.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button onClick={onClose} disabled={!copied}>
            {copied ? "Done" : "Copy the secret first"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
