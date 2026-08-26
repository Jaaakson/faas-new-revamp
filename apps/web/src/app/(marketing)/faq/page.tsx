import type { Metadata } from "next";
import Link from "next/link";

import { PageHero } from "@/components/marketing/page-hero";
import { Reveal } from "@/components/marketing/reveal";
import { Section } from "@/components/marketing/section";
import { FaqJsonLd } from "@/components/structured-data";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { faqGroups } from "@/lib/content/faq";

export const metadata: Metadata = {
  title: "FAQ",
  description:
    "Straight answers about what Fvas does, how accurate it is, what it stores, what it does not detect, and how billing works.",
  alternates: { canonical: "/faq" },
};

export default function FaqPage() {
  return (
    <>
      {/* Lets search engines surface individual answers directly in results. */}
      <FaqJsonLd />
      <PageHero
        eyebrow="FAQ"
        title="Straight answers, including the uncomfortable ones."
        description="Where a limitation exists, it is stated here rather than left for you to find during a security review."
      />

      <Section>
        <div className="grid gap-12 lg:grid-cols-[220px_1fr] lg:gap-16">
          {/* In-page nav. Real anchors, so it works before hydration and the
              browser's own find-on-page still reaches every answer. */}
          <nav aria-label="FAQ sections" className="lg:sticky lg:top-24 lg:self-start">
            <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              Sections
            </p>
            <ul className="mt-3 space-y-1">
              {faqGroups.map((group) => (
                <li key={group.title}>
                  <a
                    href={`#${slugify(group.title)}`}
                    className="text-muted-foreground hover:text-foreground focus-visible:ring-ring block rounded py-1 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                  >
                    {group.title}
                  </a>
                </li>
              ))}
            </ul>
          </nav>

          <div className="space-y-12">
            {faqGroups.map((group) => (
              <Reveal key={group.title}>
                <section id={slugify(group.title)} className="scroll-mt-24">
                  <h2 className="text-xl font-semibold tracking-tight">{group.title}</h2>
                  <Accordion type="single" collapsible className="mt-3">
                    {group.items.map((item, index) => (
                      <AccordionItem key={item.question} value={`${group.title}-${index}`}>
                        <AccordionTrigger>{item.question}</AccordionTrigger>
                        <AccordionContent>{item.answer}</AccordionContent>
                      </AccordionItem>
                    ))}
                  </Accordion>
                </section>
              </Reveal>
            ))}
          </div>
        </div>
      </Section>

      <Section className="border-t pt-0">
        <Reveal>
          <div className="flex flex-col items-start justify-between gap-6 rounded-xl border p-8 sm:flex-row sm:items-center">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">Still have a question?</h2>
              <p className="text-muted-foreground mt-2 text-sm">
                Technical questions usually get a faster answer in the docs; anything else, just
                ask.
              </p>
            </div>
            <div className="flex gap-3">
              <Button variant="outline" asChild>
                <Link href="/docs">Read the docs</Link>
              </Button>
              <Button asChild>
                <Link href="/contact">Contact us</Link>
              </Button>
            </div>
          </div>
        </Reveal>
      </Section>
    </>
  );
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
