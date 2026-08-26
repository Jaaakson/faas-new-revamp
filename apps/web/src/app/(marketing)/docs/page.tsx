import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { CodeBlock } from "@/components/code-block";
import { Card } from "@/components/ui/card";
import { docsNav } from "@/config/docs";
import { VERIFY_CURL } from "@/lib/content/code-samples";

export const metadata: Metadata = {
  title: "Documentation",
  description:
    "Integrate face authentication with Fvas: quickstart, authentication, enrollment, verification, webhooks, and the full API reference.",
  alternates: { canonical: "/docs" },
};

export default function DocsIndexPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold tracking-tight">Documentation</h1>
      <p className="text-muted-foreground mt-4 leading-7">
        Fvas answers one question with an audit trail: is the person in front of this camera the
        same person who enrolled as this subject? You enroll a face once, then verify against it as
        often as you need.
      </p>

      <h2 className="mt-10 text-xl font-semibold tracking-tight">The whole API, briefly</h2>
      <p className="text-muted-foreground mt-3 leading-7">
        Three resources — subjects, enrollments, verifications. This is the call that matters:
      </p>
      <CodeBlock code={VERIFY_CURL} lang="bash" className="mt-4" />
      <p className="text-muted-foreground mt-4 leading-7">
        A failed verification is a{" "}
        <code className="bg-muted rounded px-1 py-0.5 font-mono text-[0.875em]">200</code> with{" "}
        <code className="bg-muted rounded px-1 py-0.5 font-mono text-[0.875em]">
          &quot;decision&quot;: &quot;rejected&quot;
        </code>
        . That is a successful answer to the question you asked — only a failed <em>request</em> is
        an error.
      </p>

      <h2 className="mt-12 text-xl font-semibold tracking-tight">Start here</h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {docsNav
          .flatMap((section) => section.items)
          .filter((item) => item.href !== "/docs")
          .map((item) => (
            <Card key={item.href} className="relative h-full p-5 transition-shadow hover:shadow-md">
              <h3 className="flex items-center gap-1.5 font-medium">
                <Link
                  href={item.href}
                  className="focus-visible:ring-ring rounded after:absolute after:inset-0 focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                >
                  {item.title}
                </Link>
                <ArrowRight className="text-muted-foreground size-3.5" aria-hidden />
              </h3>
              <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">
                {item.description}
              </p>
            </Card>
          ))}
      </div>

      <h2 className="mt-12 text-xl font-semibold tracking-tight">Base URL</h2>
      <CodeBlock code="https://api.fvas.io/v1" lang="text" className="mt-4" />
      <p className="text-muted-foreground mt-4 leading-7">
        All requests use TLS. Plain HTTP is refused rather than redirected, so a misconfigured
        client fails loudly instead of sending an image in the clear once.
      </p>
    </>
  );
}
