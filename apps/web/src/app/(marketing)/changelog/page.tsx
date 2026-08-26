import type { Metadata } from "next";

import { PageHero } from "@/components/marketing/page-hero";
import { Reveal } from "@/components/marketing/reveal";
import { Section } from "@/components/marketing/section";
import { Badge } from "@/components/ui/badge";
import { changelog } from "@/lib/content/changelog";

export const metadata: Metadata = {
  title: "Changelog",
  description: "What shipped in Fvas, when, and what is still missing.",
  alternates: { canonical: "/changelog" },
};

const TYPE_VARIANT = {
  added: "success",
  changed: "info",
  fixed: "warning",
  known: "outline",
} as const;

const TYPE_LABEL = {
  added: "Added",
  changed: "Changed",
  fixed: "Fixed",
  known: "Known gap",
} as const;

export default function ChangelogPage() {
  return (
    <>
      <PageHero
        eyebrow="Changelog"
        title="What shipped, and what didn't."
        description="Every release lists its known gaps alongside its additions. A changelog that only reports wins is marketing, not a changelog."
      />

      <Section>
        <div className="space-y-16">
          {changelog.map((entry) => (
            <Reveal key={entry.version}>
              <article className="grid gap-6 lg:grid-cols-[180px_1fr] lg:gap-12">
                <div className="lg:sticky lg:top-24 lg:self-start">
                  <p className="font-mono text-sm font-medium">v{entry.version}</p>
                  <time dateTime={entry.date} className="text-muted-foreground mt-1 block text-sm">
                    {new Date(entry.date).toLocaleDateString("en-US", {
                      year: "numeric",
                      month: "long",
                      day: "numeric",
                    })}
                  </time>
                </div>

                <div>
                  <h2 className="text-2xl font-semibold tracking-tight">{entry.title}</h2>
                  <p className="text-muted-foreground mt-3 leading-relaxed">{entry.summary}</p>

                  <ul className="mt-6 space-y-3">
                    {entry.changes.map((change) => (
                      <li key={change.text} className="flex flex-wrap items-start gap-3">
                        <Badge variant={TYPE_VARIANT[change.type]} className="mt-0.5 shrink-0">
                          {TYPE_LABEL[change.type]}
                        </Badge>
                        <span className="text-muted-foreground min-w-0 flex-1 text-sm leading-relaxed">
                          {change.text}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </article>
            </Reveal>
          ))}
        </div>
      </Section>
    </>
  );
}
