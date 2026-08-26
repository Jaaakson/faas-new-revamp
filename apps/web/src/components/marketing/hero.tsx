import Link from "next/link";
import { ArrowRight, ShieldCheck } from "lucide-react";

import { CodeBlock } from "@/components/code-block";
import { VerificationResultCard } from "@/components/marketing/verification-result-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { VERIFY_CURL } from "@/lib/content/code-samples";

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      {/* Decorative gradient wash. aria-hidden and pointer-events-none so it is
          invisible to assistive tech and never intercepts a click. */}
      <div
        aria-hidden
        className="from-primary/8 pointer-events-none absolute inset-x-0 top-0 -z-10 h-[480px] bg-gradient-to-b to-transparent"
      />

      <div className="mx-auto max-w-6xl px-6 pt-16 pb-20 sm:pt-24 sm:pb-28">
        <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-16">
          <div>
            <Badge variant="outline" className="gap-1.5">
              <ShieldCheck aria-hidden />
              Templates, not photographs
            </Badge>

            <h1 className="mt-5 text-4xl font-semibold tracking-tight sm:text-5xl lg:text-[3.5rem] lg:leading-[1.05]">
              Face authentication,
              <br />
              <span className="text-primary">three API calls away.</span>
            </h1>

            <p className="text-muted-foreground mt-6 max-w-xl text-lg">
              Enroll a face. Verify in under a second. Get an audit trail your compliance team will
              actually accept — without hiring an ML team or storing a single photograph.
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              <Button size="lg" asChild>
                <Link href="/register">
                  Start free <ArrowRight />
                </Link>
              </Button>
              <Button size="lg" variant="outline" asChild>
                <Link href="/docs/quickstart">Read the quickstart</Link>
              </Button>
            </div>

            <p className="text-muted-foreground mt-6 text-sm">
              No card required · 1,000 free verifications every month
            </p>
          </div>

          {/* The product-truth panel: the request a developer writes, and the
              decision object they get back. More honest and more informative
              than a dashboard screenshot. */}
          <div className="space-y-3">
            <CodeBlock code={VERIFY_CURL} lang="bash" filename="POST /v1/verifications" />
            <VerificationResultCard />
          </div>
        </div>
      </div>
    </section>
  );
}
