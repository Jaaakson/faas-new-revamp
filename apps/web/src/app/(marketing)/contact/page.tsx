import type { Metadata } from "next";
import Link from "next/link";
import { BookOpen, Mail, ShieldAlert } from "lucide-react";

import { ContactForm } from "@/components/marketing/contact-form";
import { PageHero } from "@/components/marketing/page-hero";
import { Section } from "@/components/marketing/section";
import { Card } from "@/components/ui/card";
import { siteConfig } from "@/config/site";

export const metadata: Metadata = {
  title: "Contact",
  description:
    "Talk to us about Fvas — sales, enterprise deployments with data residency, technical support, or a security report.",
  alternates: { canonical: "/contact" },
};

export default async function ContactPage({
  searchParams,
}: {
  searchParams: Promise<{ topic?: string }>;
}) {
  const { topic } = await searchParams;

  return (
    <>
      <PageHero
        eyebrow="Contact"
        title="Tell us what you're building."
        description="The fastest answers to technical questions are usually in the docs. For everything else, this reaches a person."
      />

      <Section>
        <div className="grid gap-12 lg:grid-cols-[1.4fr_1fr] lg:gap-16">
          <ContactForm defaultTopic={topic} />

          <div className="space-y-4">
            <Card className="p-6">
              <BookOpen className="text-primary size-5" aria-hidden />
              <h2 className="mt-4 font-medium">Try the docs first</h2>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
                The quickstart takes you from signup to a verified response. Most integration
                questions are answered there in less time than an email round-trip.
              </p>
              <Link
                href="/docs/quickstart"
                className="text-primary mt-3 inline-block text-sm underline underline-offset-4"
              >
                Read the quickstart
              </Link>
            </Card>

            <Card className="p-6">
              <Mail className="text-primary size-5" aria-hidden />
              <h2 className="mt-4 font-medium">Email</h2>
              <p className="text-muted-foreground mt-2 text-sm">
                General enquiries:{" "}
                <a
                  className="text-primary underline underline-offset-4"
                  href={`mailto:${siteConfig.email}`}
                >
                  {siteConfig.email}
                </a>
              </p>
            </Card>

            <Card className="border-warning/30 p-6">
              <ShieldAlert className="text-warning size-5" aria-hidden />
              <h2 className="mt-4 font-medium">Security reports</h2>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
                Report vulnerabilities privately to{" "}
                <a
                  className="text-primary underline underline-offset-4"
                  href={`mailto:${siteConfig.security}`}
                >
                  {siteConfig.security}
                </a>
                . Never in a public issue. You will get an acknowledgement within 48 hours.
              </p>
            </Card>
          </div>
        </div>
      </Section>
    </>
  );
}
