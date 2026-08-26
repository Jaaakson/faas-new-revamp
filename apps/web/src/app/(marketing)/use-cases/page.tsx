import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Landmark, Stethoscope, Truck, Users } from "lucide-react";

import { PageHero } from "@/components/marketing/page-hero";
import { RevealGroup } from "@/components/marketing/reveal";
import { Section } from "@/components/marketing/section";
import { Card } from "@/components/ui/card";
import { useCases } from "@/lib/content/use-cases";

export const metadata: Metadata = {
  title: "Use cases",
  description:
    "How teams in digital lending, healthcare, logistics, and HR-tech use face verification as a step-up factor — with the threshold guidance and trade-offs for each.",
  alternates: { canonical: "/use-cases" },
};

const ICONS = {
  landmark: Landmark,
  stethoscope: Stethoscope,
  truck: Truck,
  users: Users,
} as const;

export default function UseCasesPage() {
  return (
    <>
      <PageHero
        eyebrow="Use cases"
        title="Where a face factor actually earns its place."
        description="Fvas is worth adding where the cost of the wrong person succeeding is high and a password cannot tell you who was there. Four patterns, with the threshold guidance and honest caveats for each."
      />

      <Section>
        <RevealGroup className="grid gap-4 md:grid-cols-2">
          {useCases.map((useCase) => {
            const Icon = ICONS[useCase.icon];
            return (
              <Card key={useCase.slug} className="h-full p-6 transition-shadow hover:shadow-md">
                <Icon className="text-primary size-5" aria-hidden />
                <h2 className="mt-4 text-lg font-medium">
                  {/* Stretched link: the whole card is the target, but the
                      accessible name stays the heading text alone. */}
                  <Link
                    href={`/use-cases/${useCase.slug}`}
                    className="focus-visible:ring-ring rounded after:absolute after:inset-0 focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                  >
                    <span className="relative">{useCase.name}</span>
                  </Link>
                </h2>
                <p className="mt-2 font-medium">{useCase.headline}</p>
                <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
                  {useCase.summary}
                </p>
                <p className="text-primary mt-4 inline-flex items-center gap-1.5 text-sm font-medium">
                  Read the pattern <ArrowRight className="size-4" aria-hidden />
                </p>
              </Card>
            );
          })}
        </RevealGroup>
      </Section>
    </>
  );
}
