"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, ScanFace, ShieldOff, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { EnrollmentWizard } from "@/components/console/enrollment-wizard";
import { ErrorState } from "@/components/console/states";
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
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type FaceProfile,
  gateLabel,
  useDeleteSubject,
  useEnrollments,
  useRevokeProfile,
  useSubject,
} from "@/features/biometrics/api";
import { absoluteTime, relativeTime } from "@/lib/format";

const STATUS_VARIANT = {
  enrolled: "success",
  pending: "warning",
  suspended: "secondary",
} as const;

const ATTEMPT_VARIANT = {
  succeeded: "success",
  failed: "destructive",
  duplicate_detected: "warning",
} as const;

export default function SubjectDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const subjectId = params.id;

  const query = useSubject(subjectId);
  const attempts = useEnrollments({ subjectId, limit: 10 });
  const deleteSubject = useDeleteSubject();
  const revokeProfile = useRevokeProfile();

  const [enrolling, setEnrolling] = React.useState(false);
  const [confirming, setConfirming] = React.useState<"delete" | "revoke" | null>(null);

  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  if (query.isLoading || !query.data) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const subject = query.data;
  const profile = subject.face_profile;

  const handleDelete = async () => {
    try {
      const result = await deleteSubject.mutateAsync(subjectId);
      toast.success("Subject deleted", {
        description: `${result.templates_destroyed} biometric template${
          result.templates_destroyed === 1 ? "" : "s"
        } permanently destroyed.`,
      });
      router.push("/dashboard/subjects");
    } catch (cause) {
      toast.error("Could not delete subject", {
        description: cause instanceof Error ? cause.message : undefined,
      });
    } finally {
      setConfirming(null);
    }
  };

  const handleRevoke = async () => {
    try {
      const result = await revokeProfile.mutateAsync(subjectId);
      toast.success("Face profile revoked", {
        description: `${result.templates_destroyed} template${
          result.templates_destroyed === 1 ? "" : "s"
        } destroyed. This subject can no longer be verified.`,
      });
      void query.refetch();
    } catch (cause) {
      toast.error("Could not revoke profile", {
        description: cause instanceof Error ? cause.message : undefined,
      });
    } finally {
      setConfirming(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
          <Link href="/dashboard/subjects">
            <ArrowLeft className="size-3.5" aria-hidden />
            Subjects
          </Link>
        </Button>

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-semibold tracking-tight">
                {subject.display_name ?? subject.external_id}
              </h1>
              <Badge
                variant={STATUS_VARIANT[subject.status as keyof typeof STATUS_VARIANT] ?? "outline"}
              >
                {subject.status}
              </Badge>
            </div>
            <p className="text-muted-foreground font-mono text-xs">{subject.external_id}</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setEnrolling(true)}>
              <ScanFace className="size-4" aria-hidden />
              {profile ? "Re-enroll" : "Enroll face"}
            </Button>
            {profile ? (
              <Button variant="outline" onClick={() => setConfirming("revoke")}>
                <ShieldOff className="size-4" aria-hidden />
                Revoke
              </Button>
            ) : null}
            <Button variant="outline" onClick={() => setConfirming("delete")}>
              <Trash2 className="size-4" aria-hidden />
              Delete
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-1">
          <h2 className="text-sm font-medium">Details</h2>
          <Separator className="my-3" />
          <dl className="space-y-2.5 text-xs">
            <Field label="Subject ID" value={<span className="font-mono">{subject.id}</span>} />
            <Field label="Verifications" value={subject.verification_count.toLocaleString()} />
            <Field
              label="Enrolled"
              value={subject.enrolled_at ? relativeTime(subject.enrolled_at) : "—"}
            />
            <Field
              label="Last verified"
              value={subject.last_verified_at ? relativeTime(subject.last_verified_at) : "Never"}
            />
            <Field label="Consent ref" value={subject.consent_reference ?? "—"} />
            <Field label="Created" value={absoluteTime(subject.created_at)} />
          </dl>
        </Card>

        <Card className="p-5 lg:col-span-2">
          <h2 className="text-sm font-medium">Face profile</h2>
          <Separator className="my-3" />
          {profile ? (
            <ProfileSummary profile={profile} />
          ) : (
            <div className="py-6 text-center">
              <p className="text-muted-foreground text-xs">
                No active face profile. This subject cannot be verified until a face is enrolled.
              </p>
              <Button size="sm" className="mt-3" onClick={() => setEnrolling(true)}>
                <ScanFace className="size-3.5" aria-hidden />
                Enroll face
              </Button>
            </div>
          )}

          {subject.profile_history.length > 1 ? (
            <>
              <Separator className="my-4" />
              <p className="text-muted-foreground mb-2 text-xs font-medium">Previous profiles</p>
              <ul className="space-y-1.5">
                {subject.profile_history
                  .filter((entry) => entry.status !== "active")
                  .map((entry) => (
                    <li
                      key={entry.id}
                      className="text-muted-foreground flex items-center gap-2 text-xs"
                    >
                      <Badge variant="outline">v{entry.version}</Badge>
                      <span>{entry.status}</span>
                      <span aria-hidden>·</span>
                      <time dateTime={entry.created_at}>{relativeTime(entry.created_at)}</time>
                    </li>
                  ))}
              </ul>
            </>
          ) : null}
        </Card>
      </div>

      <Card className="overflow-hidden">
        <div className="px-5 py-3.5">
          <h2 className="text-sm font-medium">Enrollment history</h2>
          <p className="text-muted-foreground mt-0.5 text-xs">
            Every attempt, including failures — the failure rate is what tells you whether your
            capture flow is working.
          </p>
        </div>

        {attempts.isLoading ? (
          <div className="space-y-2 px-5 pb-5">
            {Array.from({ length: 3 }, (_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </div>
        ) : (attempts.data?.data.length ?? 0) === 0 ? (
          <p className="text-muted-foreground border-t px-5 py-6 text-center text-xs">
            No enrollment attempts yet.
          </p>
        ) : (
          <div className="overflow-x-auto border-t">
            <table className="w-full text-sm">
              <caption className="sr-only">Enrollment attempts for {subject.external_id}</caption>
              <thead>
                <tr className="text-muted-foreground border-b text-left text-xs">
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Status
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Reason
                  </th>
                  <th scope="col" className="px-5 py-2.5 text-right font-medium">
                    Accepted
                  </th>
                  <th scope="col" className="px-5 py-2.5 text-right font-medium">
                    Latency
                  </th>
                  <th scope="col" className="px-5 py-2.5 text-right font-medium">
                    When
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {attempts.data?.data.map((attempt) => (
                  <tr key={attempt.id} className="hover:bg-accent/40">
                    <td className="px-5 py-2.5">
                      <Badge
                        variant={
                          ATTEMPT_VARIANT[attempt.status as keyof typeof ATTEMPT_VARIANT] ??
                          "outline"
                        }
                      >
                        {attempt.status.replace(/_/g, " ")}
                      </Badge>
                    </td>
                    <td className="text-muted-foreground px-5 py-2.5 text-xs">
                      {attempt.failure_reason ? gateLabel(attempt.failure_reason) : "—"}
                    </td>
                    <td className="px-5 py-2.5 text-right font-mono text-xs tabular-nums">
                      {attempt.accepted_count}/{attempt.image_count}
                    </td>
                    <td className="px-5 py-2.5 text-right font-mono text-xs tabular-nums">
                      {attempt.latency_ms} ms
                    </td>
                    <td className="text-muted-foreground px-5 py-2.5 text-right text-xs whitespace-nowrap">
                      <time dateTime={attempt.created_at} title={absoluteTime(attempt.created_at)}>
                        {relativeTime(attempt.created_at)}
                      </time>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Dialog open={enrolling} onOpenChange={setEnrolling}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{profile ? "Re-enroll face" : "Enroll face"}</DialogTitle>
            <DialogDescription>
              Three captures. Frames are analysed and discarded — only the mathematical templates
              are stored.
            </DialogDescription>
          </DialogHeader>
          <EnrollmentWizard
            subjectId={subjectId}
            subjectLabel={subject.display_name ?? subject.external_id}
            hasExistingProfile={!!profile}
            onComplete={() => void query.refetch()}
            onCancel={() => setEnrolling(false)}
          />
        </DialogContent>
      </Dialog>

      <Dialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {confirming === "delete" ? "Delete this subject?" : "Revoke the face profile?"}
            </DialogTitle>
            <DialogDescription>
              {confirming === "delete" ? (
                <>
                  Every biometric template is <strong>permanently destroyed</strong>. The record is
                  kept so past verifications and audit entries still resolve, and the external ID
                  becomes reusable. This cannot be undone.
                </>
              ) : (
                <>
                  The templates are destroyed and this subject can no longer be verified. The
                  profile is kept as history, but it cannot be reinstated — they would need to
                  enroll again.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={deleteSubject.isPending || revokeProfile.isPending}
              onClick={() => void (confirming === "delete" ? handleDelete() : handleRevoke())}
            >
              {confirming === "delete" ? "Delete permanently" : "Revoke profile"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted-foreground shrink-0">{label}</dt>
      <dd className="truncate text-right">{value}</dd>
    </div>
  );
}

function ProfileSummary({ profile }: { profile: FaceProfile }) {
  return (
    <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <Stat label="Version" value={`v${profile.version}`} />
      <Stat label="Templates" value={String(profile.template_count)} />
      <Stat
        label="Avg quality"
        value={
          profile.avg_quality_score !== null
            ? `${(profile.avg_quality_score * 100).toFixed(0)}%`
            : "—"
        }
      />
      <Stat label="Model" value={profile.model.version} mono />
    </dl>
  );
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className={`mt-0.5 text-sm font-medium ${mono ? "font-mono text-xs" : ""}`}>{value}</dd>
    </div>
  );
}
