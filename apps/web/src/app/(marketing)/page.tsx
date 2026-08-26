import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  Copy,
  Fingerprint,
  KeyRound,
  ScanFace,
  ScrollText,
  Share2,
  ShieldCheck,
  Trash2,
  UserRoundPlus,
  Webhook,
} from "lucide-react";

import { CodeBlock } from "@/components/code-block";
import { CodeTabs } from "@/components/marketing/code-tabs";
import { Hero } from "@/components/marketing/hero";
import { Reveal, RevealGroup } from "@/components/marketing/reveal";
import { Section, SectionHeader } from "@/components/marketing/section";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  CREATE_SUBJECT,
  ENROLL,
  VERIFY_CURL,
  VERIFY_GO,
  VERIFY_NODE,
  VERIFY_PYTHON,
  VERIFY_RESPONSE,
} from "@/lib/content/code-samples";
import { topFaqs } from "@/lib/content/faq";
import { plans } from "@/lib/content/pricing";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  // `absolute` bypasses the root layout's "%s · Fvas" template, which would
  // otherwise render "Fvas — Face Authentication Platform · Fvas".
  title: { absolute: "Fvas — Face Authentication Platform" },
  description:
    "Add face authentication to any application with three API calls. Enroll a subject, verify in under a second, and get an audit trail your compliance team will accept.",
  alternates: { canonical: "/" },
};

export default function HomePage() {
  return (
    <>
      <Hero />

      {/* ── Problem ────────────────────────────────────────────────────── */}
      <Section className="border-t">
        <SectionHeader
          eyebrow="The problem"
          title="Passwords prove possession. Not identity."
          description="Every factor most applications ship verifies something a person has, not who they are. That gap is where account takeover lives."
        />

        <RevealGroup className="mt-12 grid gap-4 sm:grid-cols-3">
          {[
            {
              icon: Share2,
              title: "Credentials are transferable",
              body: "A password, an OTP, or a session token works identically in anyone's hands. Nothing about it is tied to a person.",
            },
            {
              icon: Fingerprint,
              title: "Phishing scales, faces don't",
              body: "A convincing login page harvests thousands of credentials in an afternoon. It cannot harvest the person.",
            },
            {
              icon: ScrollText,
              title: "No evidence after the fact",
              body: "When a disputed transaction lands on a risk team's desk, an access log shows a session — not who was actually there.",
            },
          ].map((item) => (
            <Card key={item.title} className="h-full p-6">
              <item.icon className="text-primary size-5" aria-hidden />
              <h3 className="mt-4 font-medium">{item.title}</h3>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{item.body}</p>
            </Card>
          ))}
        </RevealGroup>
      </Section>

      {/* ── How it works ───────────────────────────────────────────────── */}
      <Section className="bg-muted/40 border-t">
        <SectionHeader
          eyebrow="How it works"
          title="Three calls, start to finish."
          description="Create a subject, enroll their face once, then verify as often as you need. There is no fourth concept to learn."
        />

        <div className="mt-12 space-y-8">
          <Step
            number={1}
            icon={UserRoundPlus}
            title="Create a subject"
            body="A subject is one of your end users. You identify them with your own ID, so nothing in your database has to change."
            code={<CodeBlock code={CREATE_SUBJECT} lang="bash" />}
          />
          <Step
            number={2}
            icon={ScanFace}
            title="Enroll their face"
            body="Send one to five frames. Quality gates run before anything is stored, so a blurry capture is rejected with a reason instead of quietly poisoning every future match."
            code={<CodeBlock code={ENROLL} lang="bash" />}
          />
          <Step
            number={3}
            icon={ShieldCheck}
            title="Verify, and act on the decision"
            body="You get a decision, the score, and the threshold it was measured against. A rejection always states why."
            code={<CodeBlock code={VERIFY_RESPONSE} lang="json" />}
          />
        </div>
      </Section>

      {/* ── Features (bento) ───────────────────────────────────────────── */}
      <Section className="border-t">
        <SectionHeader
          eyebrow="What you get"
          title="Everything around the model is the hard part."
          description="Face matching is a solved research problem. Quality gates, tenancy, thresholds, and auditability are what make it usable in production."
        />

        <div className="mt-12 grid gap-4 md:grid-cols-3">
          <Reveal className="md:col-span-2">
            <Card className="h-full p-6">
              <Badge variant="success">Signature control</Badge>
              <h3 className="mt-4 text-lg font-medium">Every decision shows its margin</h3>
              <p className="text-muted-foreground mt-2 max-w-lg text-sm leading-relaxed">
                A bare boolean throws away information your risk engine could use. Every response
                carries the similarity, the threshold applied, and a confidence band — so a marginal
                pass on a large transfer can trigger a second factor instead of sailing through.
              </p>

              <div className="mt-6 space-y-3">
                <ScoreRow label="verified" score={0.81} threshold={0.38} tone="success" />
                <ScoreRow
                  label="verified"
                  score={0.42}
                  threshold={0.38}
                  tone="warning"
                  note="low confidence"
                />
                <ScoreRow label="rejected" score={0.21} threshold={0.38} tone="destructive" />
              </div>
            </Card>
          </Reveal>

          <Reveal delay={0.06}>
            <Card className="h-full p-6">
              <ShieldCheck className="text-chart-2 size-5" aria-hidden />
              <h3 className="mt-4 text-lg font-medium">Quality gates first</h3>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
                Seven checks run before matching. A failure returns a specific reason, never a wrong
                answer.
              </p>
              <ul className="mt-4 space-y-1.5 text-sm">
                {[
                  "Single face in frame",
                  "Inter-ocular distance ≥ 112px",
                  "Sharpness and blur",
                  "Brightness and contrast",
                  "Head pose within range",
                  "Occlusion",
                  "Detector confidence",
                ].map((check) => (
                  <li key={check} className="text-muted-foreground flex items-center gap-2">
                    <span className="bg-chart-2 size-1.5 shrink-0 rounded-full" aria-hidden />
                    {check}
                  </li>
                ))}
              </ul>
            </Card>
          </Reveal>

          <Reveal delay={0.12}>
            <Card className="h-full p-6">
              <Copy className="text-chart-3 size-5" aria-hidden />
              <h3 className="mt-4 text-lg font-medium">Duplicate detection</h3>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
                Vector search catches one face enrolling under two identities. Surfaced as a
                decision with the matching subject, not a silent block — legitimate cases exist, and
                a human should choose.
              </p>
            </Card>
          </Reveal>

          <Reveal delay={0.18}>
            <Card className="h-full p-6">
              <Webhook className="text-chart-4 size-5" aria-hidden />
              <h3 className="mt-4 text-lg font-medium">Signed webhooks</h3>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
                HMAC-SHA256 over a timestamped payload, so a captured request cannot be replayed
                later. Eight retries with backoff over 24 hours.
              </p>
            </Card>
          </Reveal>

          <Reveal delay={0.24}>
            <Card className="h-full p-6">
              <ScrollText className="text-chart-5 size-5" aria-hidden />
              <h3 className="mt-4 text-lg font-medium">Audit log, not an afterthought</h3>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
                Append-only, written in the same transaction as the change it records, and
                exportable. The threshold in force is stored per session, so an auditor asking about
                March gets March&apos;s answer.
              </p>
            </Card>
          </Reveal>
        </div>
      </Section>

      {/* ── Developer ──────────────────────────────────────────────────── */}
      <Section className="bg-muted/40 border-t">
        <div className="grid items-start gap-12 lg:grid-cols-2">
          <Reveal>
            <p className="text-primary text-sm font-medium">For developers</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
              Integrate in an afternoon.
            </h2>
            <p className="text-muted-foreground mt-4 text-lg">
              One endpoint does the work. The rest is your own business logic.
            </p>

            <ul className="mt-8 space-y-4">
              {[
                {
                  title: "Test mode is a key, not a second URL",
                  body: "Test keys write real data behind a banner in your dashboard, and never touch billing or production analytics.",
                },
                {
                  title: "One error envelope, everywhere",
                  body: "Stable machine-readable codes, structured details, and a request ID that resolves a support ticket in one query.",
                },
                {
                  title: "Idempotency built in",
                  body: "A retried network call cannot double-charge your quota or create a second profile.",
                },
                {
                  title: "OpenAPI generated from the implementation",
                  body: "The schema cannot drift from the code, so generated clients stay correct.",
                },
              ].map((item) => (
                <li key={item.title} className="flex gap-3">
                  <ArrowRight className="text-primary mt-1 size-4 shrink-0" aria-hidden />
                  <div>
                    <p className="font-medium">{item.title}</p>
                    <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
                      {item.body}
                    </p>
                  </div>
                </li>
              ))}
            </ul>

            <Button className="mt-8" variant="outline" asChild>
              <Link href="/docs">
                Browse the docs <ArrowRight />
              </Link>
            </Button>
          </Reveal>

          <Reveal delay={0.1}>
            <CodeTabs
              items={[
                {
                  value: "curl",
                  label: "cURL",
                  content: <CodeBlock code={VERIFY_CURL} lang="bash" />,
                },
                {
                  value: "node",
                  label: "Node",
                  content: <CodeBlock code={VERIFY_NODE} lang="typescript" />,
                },
                {
                  value: "python",
                  label: "Python",
                  content: <CodeBlock code={VERIFY_PYTHON} lang="python" />,
                },
                { value: "go", label: "Go", content: <CodeBlock code={VERIFY_GO} lang="go" /> },
              ]}
            />
          </Reveal>
        </div>
      </Section>

      {/* ── Security strip ─────────────────────────────────────────────── */}
      <Section className="border-t">
        <SectionHeader
          eyebrow="Security & privacy"
          title="Biometric data is irrevocable. We treat it that way."
          description="A leaked password can be changed. A leaked face cannot. Every design decision below follows from that."
        />

        <RevealGroup className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            {
              icon: Fingerprint,
              title: "Templates, not photographs",
              body: "Images become a 512-dimension vector and are then discarded. Retention is opt-in and off by default.",
            },
            {
              icon: KeyRound,
              title: "Scoped, revocable keys",
              body: "Hashed at rest, separated by environment, revocable instantly, with IP allowlisting available.",
            },
            {
              icon: Trash2,
              title: "Deletion is physical",
              body: "Template rows are deleted, not flagged. A soft-deleted biometric template is still retained biometric data.",
            },
            {
              icon: ScrollText,
              title: "RBAC and audit",
              body: "Four roles, permission-checked endpoints, and an append-only audit log a compliance officer can export.",
            },
          ].map((item) => (
            <Card key={item.title} className="h-full p-6">
              <item.icon className="text-primary size-5" aria-hidden />
              <h3 className="mt-4 font-medium">{item.title}</h3>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{item.body}</p>
            </Card>
          ))}
        </RevealGroup>

        {/* Stated on the marketing page, not buried in a FAQ. A prospect who
            discovers this during a security review does not come back. */}
        <Reveal className="mt-8">
          <div className="border-warning/30 bg-warning/5 rounded-lg border p-5">
            <p className="text-sm font-medium">What this release does not do</p>
            <p className="text-muted-foreground mt-2 max-w-3xl text-sm leading-relaxed">
              Fvas ships quality gates, screen-replay heuristics, and an optional active challenge —
              but it is{" "}
              <strong className="text-foreground">
                not certified presentation-attack detection
              </strong>{" "}
              under ISO/IEC 30107-3. It is built for step-up authentication inside a session you
              already control, not as the sole control for unsupervised remote onboarding against a
              motivated attacker. Certified liveness is the top item on our roadmap.
            </p>
          </div>
        </Reveal>
      </Section>

      {/* ── Pricing teaser ─────────────────────────────────────────────── */}
      <Section className="bg-muted/40 border-t">
        <SectionHeader
          align="center"
          eyebrow="Pricing"
          title="Priced per verification, not per seat."
          description="Enrollments are always free. You pay for the action that carries the value."
        />

        <RevealGroup className="mt-12 grid gap-4 md:grid-cols-3">
          {plans.slice(0, 3).map((plan) => (
            <Card
              key={plan.id}
              className={cn("relative h-full p-6", plan.featured && "border-primary shadow-md")}
            >
              {plan.featured ? (
                <Badge className="absolute -top-2.5 left-6">Most popular</Badge>
              ) : null}
              <h3 className="font-medium">{plan.name}</h3>
              <p className="mt-3">
                <span className="text-3xl font-semibold tracking-tight">{plan.priceLabel}</span>
                <span className="text-muted-foreground ml-1.5 text-sm">{plan.cadence}</span>
              </p>
              <p className="text-muted-foreground mt-3 text-sm">{plan.description}</p>
              <p className="mt-4 text-sm font-medium">
                {plan.verifications?.toLocaleString()} verifications / month
              </p>
              <Button
                className="mt-5 w-full"
                variant={plan.featured ? "default" : "outline"}
                asChild
              >
                <Link href={plan.cta.href}>{plan.cta.label}</Link>
              </Button>
            </Card>
          ))}
        </RevealGroup>

        <Reveal className="mt-8 text-center">
          <Button variant="ghost" asChild>
            <Link href="/pricing">
              Compare all plans and estimate your cost <ArrowRight />
            </Link>
          </Button>
        </Reveal>
      </Section>

      {/* ── FAQ ────────────────────────────────────────────────────────── */}
      <Section className="border-t">
        <div className="grid gap-12 lg:grid-cols-[1fr_1.6fr]">
          <SectionHeader
            title="Questions, answered directly."
            description={
              <>
                More in the{" "}
                <Link href="/faq" className="text-primary underline underline-offset-4">
                  full FAQ
                </Link>
                .
              </>
            }
          />
          <Reveal>
            <Accordion type="single" collapsible className="w-full">
              {topFaqs.map((faq, index) => (
                <AccordionItem key={faq.question} value={`item-${index}`}>
                  <AccordionTrigger>{faq.question}</AccordionTrigger>
                  <AccordionContent>{faq.answer}</AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </Reveal>
        </div>
      </Section>

      {/* ── Closing CTA ────────────────────────────────────────────────── */}
      <Section className="border-t">
        <Reveal>
          <div className="from-primary/10 rounded-xl border bg-gradient-to-br to-transparent px-6 py-14 text-center sm:px-12">
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
              Run your first verification today.
            </h2>
            <p className="text-muted-foreground mx-auto mt-4 max-w-xl text-lg">
              A thousand free verifications every month, no card, and a working curl command before
              you finish signing up.
            </p>
            <Button size="lg" className="mt-8" asChild>
              <Link href="/register">
                Start free <ArrowRight />
              </Link>
            </Button>
          </div>
        </Reveal>
      </Section>
    </>
  );
}

function Step({
  number,
  icon: Icon,
  title,
  body,
  code,
}: {
  number: number;
  icon: React.ElementType;
  title: string;
  body: string;
  code: React.ReactNode;
}) {
  return (
    <Reveal>
      <div className="grid gap-6 lg:grid-cols-[1fr_1.3fr] lg:items-center">
        <div className="flex gap-4">
          <div className="bg-primary/10 text-primary flex size-9 shrink-0 items-center justify-center rounded-full font-mono text-sm font-medium">
            {number}
          </div>
          <div>
            <h3 className="flex items-center gap-2 text-lg font-medium">
              <Icon className="text-muted-foreground size-4" aria-hidden />
              {title}
            </h3>
            <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{body}</p>
          </div>
        </div>
        {code}
      </div>
    </Reveal>
  );
}

function ScoreRow({
  label,
  score,
  threshold,
  tone,
  note,
}: {
  label: string;
  score: number;
  threshold: number;
  tone: "success" | "warning" | "destructive";
  note?: string;
}) {
  const barColor = {
    success: "bg-success",
    warning: "bg-warning",
    destructive: "bg-destructive",
  }[tone];

  const textColor = {
    success: "text-success",
    warning: "text-warning",
    destructive: "text-destructive",
  }[tone];

  return (
    <div className="flex items-center gap-3">
      <span className={cn("w-20 shrink-0 text-xs font-medium", textColor)}>{label}</span>
      <div className="bg-muted relative h-1.5 flex-1 rounded-full">
        <div className={cn("h-full rounded-full", barColor)} style={{ width: `${score * 100}%` }} />
        <div
          className="bg-foreground absolute -top-1 h-3.5 w-px"
          style={{ left: `${threshold * 100}%` }}
          aria-hidden
        />
      </div>
      <span className="text-muted-foreground w-24 shrink-0 text-right font-mono text-xs tabular-nums">
        {score.toFixed(2)}
        {note ? <span className="ml-1 hidden sm:inline">· {note}</span> : null}
      </span>
    </div>
  );
}
