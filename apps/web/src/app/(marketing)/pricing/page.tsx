import * as React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { Check, Minus } from "lucide-react";

import { PageHero } from "@/components/marketing/page-hero";
import { QuotaCalculator } from "@/components/marketing/quota-calculator";
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
import { faqGroups } from "@/lib/content/faq";
import { comparison, plans } from "@/lib/content/pricing";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Usage-based pricing from $0. Pay per verification, never per seat — enrollments are always free. Estimate your monthly cost with the calculator.",
  alternates: { canonical: "/pricing" },
};

const billingFaqs = faqGroups.find((group) => group.title === "Billing")?.items ?? [];

export default function PricingPage() {
  return (
    <>
      <PageHero
        eyebrow="Pricing"
        title="Pricing that tracks your usage, not your headcount."
        description="You pay for verifications — the action that carries the value. Enrollments are free, because charging for onboarding suppresses the adoption that produces verification volume."
      />

      <Section className="pb-0">
        <RevealGroup className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {plans.map((plan) => (
            <Card
              key={plan.id}
              className={cn(
                "relative flex h-full flex-col p-6",
                plan.featured && "border-primary shadow-md",
              )}
            >
              {plan.featured ? (
                <Badge className="absolute -top-2.5 left-6">Most popular</Badge>
              ) : null}

              <h2 className="font-medium">{plan.name}</h2>
              <p className="mt-3">
                <span className="text-3xl font-semibold tracking-tight">{plan.priceLabel}</span>
                <span className="text-muted-foreground ml-1.5 text-sm">{plan.cadence}</span>
              </p>
              <p className="text-muted-foreground mt-3 min-h-10 text-sm">{plan.description}</p>

              <Button
                className="mt-5 w-full"
                variant={plan.featured ? "default" : "outline"}
                asChild
              >
                <Link href={plan.cta.href}>{plan.cta.label}</Link>
              </Button>

              <ul className="mt-6 space-y-2.5 text-sm">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex gap-2">
                    <Check className="text-success mt-0.5 size-4 shrink-0" aria-hidden />
                    <span className="text-muted-foreground">{feature}</span>
                  </li>
                ))}
              </ul>

              {plan.overage ? (
                <p className="text-muted-foreground mt-auto pt-6 text-xs">
                  Then ${plan.overage.toFixed(3)} per additional verification.
                </p>
              ) : null}
            </Card>
          ))}
        </RevealGroup>
      </Section>

      <Section>
        <SectionHeader
          eyebrow="Estimate"
          title="What will this actually cost me?"
          description="Move the slider. No form, no sales call."
        />
        <Reveal className="mt-10">
          <QuotaCalculator />
        </Reveal>
      </Section>

      <Section className="bg-muted/40 border-t">
        <SectionHeader title="Compare every plan" />

        <Reveal className="mt-10">
          {/* Wide tables scroll inside their own container; the page body never
              scrolls horizontally. */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-3xl border-separate border-spacing-0 text-sm">
              <caption className="sr-only">Feature comparison across all plans</caption>
              <thead>
                <tr>
                  <th
                    scope="col"
                    className="bg-muted/40 sticky left-0 border-b py-3 pr-4 text-left font-medium"
                  >
                    <span className="sr-only">Feature</span>
                  </th>
                  {plans.map((plan) => (
                    <th
                      key={plan.id}
                      scope="col"
                      className="border-b px-4 py-3 text-left font-medium"
                    >
                      {plan.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {comparison.map((group) => (
                  <React.Fragment key={group.group}>
                    <tr>
                      <th
                        scope="colgroup"
                        colSpan={plans.length + 1}
                        className="text-muted-foreground pt-8 pb-2 text-left text-xs font-medium tracking-wide uppercase"
                      >
                        {group.group}
                      </th>
                    </tr>
                    {group.rows.map((row) => (
                      <tr key={row.label}>
                        <th
                          scope="row"
                          className="text-muted-foreground border-b py-3 pr-4 text-left font-normal"
                        >
                          {row.label}
                        </th>
                        {row.values.map((value, index) => (
                          <td key={index} className="border-b px-4 py-3">
                            {typeof value === "boolean" ? (
                              value ? (
                                <>
                                  <Check className="text-success size-4" aria-hidden />
                                  <span className="sr-only">Included</span>
                                </>
                              ) : (
                                <>
                                  <Minus className="text-muted-foreground size-4" aria-hidden />
                                  <span className="sr-only">Not included</span>
                                </>
                              )
                            ) : (
                              <span className="tabular-nums">{value}</span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>
      </Section>

      <Section className="border-t">
        <div className="grid gap-12 lg:grid-cols-[1fr_1.6fr]">
          <SectionHeader title="Billing questions" />
          <Reveal>
            <Accordion type="single" collapsible>
              {billingFaqs.map((faq, index) => (
                <AccordionItem key={faq.question} value={`billing-${index}`}>
                  <AccordionTrigger>{faq.question}</AccordionTrigger>
                  <AccordionContent>{faq.answer}</AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </Reveal>
        </div>
      </Section>

      <Section className="border-t pt-0">
        <Reveal>
          <div className="flex flex-col items-start justify-between gap-6 rounded-xl border p-8 sm:flex-row sm:items-center">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">
                Need data residency, on-premise, or SSO?
              </h2>
              <p className="text-muted-foreground mt-2 max-w-xl text-sm">
                Enterprise covers regulated deployments — including running Fvas entirely inside
                your own network.
              </p>
            </div>
            <Button asChild>
              <Link href="/contact?topic=enterprise">Contact sales</Link>
            </Button>
          </div>
        </Reveal>
      </Section>
    </>
  );
}
