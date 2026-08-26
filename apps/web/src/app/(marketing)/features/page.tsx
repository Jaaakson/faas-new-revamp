import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  Building2,
  ChartNoAxesColumn,
  Copy,
  Gauge,
  KeyRound,
  ScanFace,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  TriangleAlert,
  UserRoundPlus,
  Webhook,
} from "lucide-react";

import { CodeBlock } from "@/components/code-block";
import { PageHero } from "@/components/marketing/page-hero";
import { Reveal, RevealGroup } from "@/components/marketing/reveal";
import { Section, SectionHeader } from "@/components/marketing/section";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { INCONCLUSIVE_RESPONSE, REJECTED_RESPONSE } from "@/lib/content/code-samples";

export const metadata: Metadata = {
  title: "Features",
  description:
    "Quality gates, per-organization thresholds, duplicate detection, multi-tenancy, RBAC, signed webhooks, and an audit log built for evidence — everything around the model that makes face matching usable in production.",
  alternates: { canonical: "/features" },
};

const CAPABILITIES = [
  {
    icon: UserRoundPlus,
    title: "Guided multi-shot enrollment",
    body: "One to five frames per subject, captured with live quality coaching. Multiple templates covering different poses measurably reduce false rejection later, and enrollment happens once while verification happens thousands of times.",
  },
  {
    icon: ShieldCheck,
    title: "Seven quality gates before matching",
    body: "Face size, sharpness, brightness, contrast, pose, occlusion, and detector confidence. Gates are stricter at enrollment than at verification, because someone enrolling can retry and someone authenticating at 11pm in a warehouse cannot.",
  },
  {
    icon: SlidersHorizontal,
    title: "Thresholds you can defend",
    body: "Three presets plus a custom value on Growth. Every response records the threshold that was applied, so changing your configuration never rewrites the history an auditor reads.",
  },
  {
    icon: Copy,
    title: "Duplicate face detection",
    body: "Vector search across your tenant catches one person enrolling under two identities. Returned as a 409 naming the matching subject and the similarity, so a human makes the call and the decision is logged.",
  },
  {
    icon: Gauge,
    title: "Latency you can see",
    body: "Every response carries a timing breakdown across detection, embedding, and matching. Our p95 target is under 800 ms and you can verify it on your own traffic rather than trusting a benchmark.",
  },
  {
    icon: Building2,
    title: "Multi-tenancy from day one",
    body: "Organizations, memberships, and four roles. If you are a platform, one Fvas organization per customer maps cleanly onto your own tenancy model.",
  },
  {
    icon: KeyRound,
    title: "Keys built for rotation",
    body: "Separate test and live keys, scoped permissions, optional IP allowlisting, and a 24-hour overlap on rotation so you can roll a key through a deploy without an outage window.",
  },
  {
    icon: Webhook,
    title: "Webhooks that survive failure",
    body: "HMAC-SHA256 signatures over a timestamped payload, eight retries with exponential backoff across 24 hours, a delivery log you can inspect, and automatic disabling after sustained failure.",
  },
  {
    icon: ChartNoAxesColumn,
    title: "Analytics that produce decisions",
    body: "Volume, outcome split, failure-reason breakdown, latency distribution, and a success-rate heatmap by hour of day — which is how you discover that your night shift has a lighting problem, not a fraud problem.",
  },
  {
    icon: ScrollText,
    title: "An audit log meant as evidence",
    body: "Append-only, written in the same transaction as the change it records, redacted of secrets, and exportable. The application role has no UPDATE or DELETE grant on it.",
  },
];

export default function FeaturesPage() {
  return (
    <>
      <PageHero
        eyebrow="Features"
        title="The model is the easy part."
        description="Face matching is solved research. What makes it usable in production is everything around it — and that is what Fvas is."
      >
        <div className="flex flex-wrap gap-3">
          <Button asChild>
            <Link href="/register">
              Start free <ArrowRight />
            </Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/docs">Read the docs</Link>
          </Button>
        </div>
      </PageHero>

      <Section>
        <RevealGroup className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map((item) => (
            <Card key={item.title} className="h-full p-6">
              <item.icon className="text-primary size-5" aria-hidden />
              <h2 className="mt-4 font-medium">{item.title}</h2>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{item.body}</p>
            </Card>
          ))}
        </RevealGroup>
      </Section>

      {/* Three-way outcome — the single most consequential API design choice. */}
      <Section className="bg-muted/40 border-t">
        <SectionHeader
          eyebrow="Decisions"
          title="Three outcomes, because two would lie."
          description="Most face APIs return a boolean. That collapses “this is not the right person” and “the room is too dark” into one answer, and corrupts your fraud metrics with lighting problems."
        />

        <div className="mt-12 grid gap-6 lg:grid-cols-3">
          <Reveal>
            <Card className="h-full p-6">
              <Badge variant="success">verified</Badge>
              <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
                Similarity met or exceeded the threshold. The response includes a confidence band,
                so a marginal pass on a high-value action can trigger a second factor rather than
                sailing through.
              </p>
            </Card>
          </Reveal>

          <Reveal delay={0.06}>
            <Card className="h-full p-6">
              <Badge variant="destructive">rejected</Badge>
              <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
                A good capture of the wrong person. This is a real signal and belongs in your fraud
                metrics.
              </p>
              <CodeBlock code={REJECTED_RESPONSE} lang="json" className="mt-4" copyable={false} />
            </Card>
          </Reveal>

          <Reveal delay={0.12}>
            <Card className="h-full p-6">
              <Badge variant="warning">inconclusive</Badge>
              <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
                No face, several faces, or a capture that failed a quality gate. Not a fraud signal
                — a capture problem, with the specific gate named.
              </p>
              <CodeBlock
                code={INCONCLUSIVE_RESPONSE}
                lang="json"
                className="mt-4"
                copyable={false}
              />
            </Card>
          </Reveal>
        </div>
      </Section>

      <Section className="border-t">
        <SectionHeader
          eyebrow="Roadmap"
          title="What we have not built yet."
          description="Stated here rather than discovered during your security review."
        />

        <RevealGroup className="mt-10 grid gap-4 sm:grid-cols-2">
          {[
            {
              title: "Certified liveness (PAD)",
              body: "Quality gates, screen-replay heuristics, and an optional active challenge ship today. ISO/IEC 30107-3 certification does not. This is the top roadmap item.",
            },
            {
              title: "Mobile SDKs",
              body: "Browser capture proves the flow and the API works from any language. Native iOS and Android SDKs are a distribution investment we have not made yet.",
            },
            {
              title: "1:N identification at scale",
              body: "Searching a population for an unknown face is a different product with a different cost curve. Today, 1:N runs only within your tenant, only for duplicate detection.",
            },
            {
              title: "SSO, SAML, and SCIM",
              body: "Enterprise procurement features. Available on request as part of an Enterprise engagement.",
            },
          ].map((item) => (
            <Card key={item.title} className="h-full p-6">
              <TriangleAlert className="text-warning size-5" aria-hidden />
              <h3 className="mt-4 font-medium">{item.title}</h3>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{item.body}</p>
            </Card>
          ))}
        </RevealGroup>
      </Section>

      <Section className="border-t">
        <Reveal>
          <div className="from-primary/10 rounded-xl border bg-gradient-to-br to-transparent px-6 py-14 text-center sm:px-12">
            <ScanFace className="text-primary mx-auto size-8" aria-hidden />
            <h2 className="mt-5 text-3xl font-semibold tracking-tight">
              See it work on your own data.
            </h2>
            <p className="text-muted-foreground mx-auto mt-4 max-w-xl">
              A thousand free verifications a month. Enroll from the dashboard camera or straight
              from the API — whichever you prefer.
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
