import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, Check, SlidersHorizontal, Target, TriangleAlert, Zap } from "lucide-react";

import { PageHero } from "@/components/marketing/page-hero";
import { Reveal } from "@/components/marketing/reveal";
import { Section } from "@/components/marketing/section";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { getUseCase, useCases } from "@/lib/content/use-cases";

/** Static params make every vertical page a prerendered file at build time. */
export function generateStaticParams() {
  return useCases.map((useCase) => ({ slug: useCase.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const useCase = getUseCase(slug);
  if (!useCase) return {};

  return {
    title: useCase.name,
    description: useCase.summary,
    alternates: { canonical: `/use-cases/${useCase.slug}` },
  };
}

export default async function UseCasePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const useCase = getUseCase(slug);
  if (!useCase) notFound();

  const others = useCases.filter((item) => item.slug !== useCase.slug);

  return (
    <>
      <PageHero eyebrow={useCase.name} title={useCase.headline} description={useCase.summary} />

      <Section>
        <div className="grid gap-10 lg:grid-cols-[1.5fr_1fr] lg:gap-16">
          <div className="space-y-10">
            <Reveal>
              <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
                <Target className="text-primary size-5" aria-hidden />
                What triggers the need
              </h2>
              <p className="text-muted-foreground mt-3 leading-relaxed">{useCase.trigger}</p>
            </Reveal>

            <Reveal>
              <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
                <Zap className="text-primary size-5" aria-hidden />
                Where it goes in your flow
              </h2>
              <p className="text-muted-foreground mt-3 leading-relaxed">
                {useCase.integrationPoint}
              </p>
            </Reveal>

            <Reveal>
              <h2 className="text-xl font-semibold tracking-tight">What you get</h2>
              <ul className="mt-4 space-y-3">
                {useCase.outcomes.map((outcome) => (
                  <li key={outcome} className="flex gap-3">
                    <Check className="text-success mt-0.5 size-4 shrink-0" aria-hidden />
                    <span className="text-muted-foreground text-sm leading-relaxed">{outcome}</span>
                  </li>
                ))}
              </ul>
            </Reveal>

            <Reveal>
              <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
                <TriangleAlert className="text-warning size-5" aria-hidden />
                Worth knowing before you commit
              </h2>
              <ul className="mt-4 space-y-3">
                {useCase.considerations.map((item) => (
                  <li key={item} className="text-muted-foreground text-sm leading-relaxed">
                    — {item}
                  </li>
                ))}
              </ul>
            </Reveal>
          </div>

          <div className="space-y-4 lg:sticky lg:top-24 lg:self-start">
            <Card className="p-6">
              <SlidersHorizontal className="text-primary size-5" aria-hidden />
              <h2 className="mt-4 font-medium">Recommended threshold</h2>
              <p className="mt-3 font-mono text-2xl font-semibold tabular-nums">
                {useCase.threshold.value}
              </p>
              <p className="text-muted-foreground text-sm">{useCase.threshold.preset} preset</p>
              <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
                {useCase.threshold.reason}
              </p>
              <p className="text-muted-foreground mt-4 text-xs">
                A starting point, not a result. Calibrate against your own traffic once you have a
                few thousand verifications.
              </p>
            </Card>

            <Card className="p-6">
              <h2 className="font-medium">Try it on your own data</h2>
              <p className="text-muted-foreground mt-2 text-sm">
                1,000 free verifications a month, no card.
              </p>
              <Button className="mt-4 w-full" asChild>
                <Link href="/register">
                  Start free <ArrowRight />
                </Link>
              </Button>
              <Button variant="outline" className="mt-2 w-full" asChild>
                <Link href="/contact">Talk to us first</Link>
              </Button>
            </Card>
          </div>
        </div>
      </Section>

      <Section className="bg-muted/40 border-t">
        <h2 className="text-xl font-semibold tracking-tight">Other patterns</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-3">
          {others.map((item) => (
            <Card key={item.slug} className="relative h-full p-5 transition-shadow hover:shadow-md">
              <h3 className="font-medium">
                <Link
                  href={`/use-cases/${item.slug}`}
                  className="focus-visible:ring-ring rounded after:absolute after:inset-0 focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                >
                  {item.name}
                </Link>
              </h3>
              <p className="text-muted-foreground mt-2 text-sm">{item.headline}</p>
            </Card>
          ))}
        </div>
      </Section>
    </>
  );
}
