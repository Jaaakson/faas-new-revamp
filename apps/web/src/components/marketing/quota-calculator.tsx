"use client";

import * as React from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { recommendPlan } from "@/lib/content/pricing";

/**
 * Volume → recommended plan and true monthly cost.
 *
 * Usage-based pricing creates purchase anxiety: a buyer cannot tell what they
 * will actually pay. Letting them resolve that here, rather than by emailing
 * sales, follows the same self-serve principle as the rest of the product.
 *
 * The slider is logarithmic because the interesting range spans 100 to
 * 2,000,000. A linear scale would compress every realistic starting volume into
 * the first two percent of the track.
 */
const MIN_EXP = 2; // 100
const MAX_EXP = 6.3; // ~2,000,000

function expToVolume(exp: number): number {
  const raw = 10 ** exp;
  // Round to a human-looking number so the readout never says "27,431".
  const magnitude = 10 ** Math.floor(Math.log10(raw) - 1);
  return Math.max(100, Math.round(raw / magnitude) * magnitude);
}

export function QuotaCalculator() {
  const [exp, setExp] = React.useState(4); // 10,000
  const volume = expToVolume(exp);
  const result = recommendPlan(volume);

  const currency = (value: number) =>
    value.toLocaleString("en-US", { style: "currency", currency: "USD" });

  return (
    <Card className="p-6 sm:p-8">
      <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr] lg:items-center">
        <div>
          {/* Not a <label htmlFor>: the Radix slider's focusable element is a
              span with role="slider", which is not a labelable element. The
              association is made with aria-labelledby instead. */}
          <span id="volume-label" className="text-sm font-medium">
            Expected verifications per month
          </span>
          <p className="text-muted-foreground mt-1 text-sm">
            Enrollments are free, so count only the times you check a face.
          </p>

          <p className="mt-6 font-mono text-4xl font-semibold tabular-nums">
            {volume.toLocaleString()}
          </p>

          <Slider
            className="mt-6"
            min={MIN_EXP}
            max={MAX_EXP}
            step={0.05}
            value={[exp]}
            onValueChange={([next]) => setExp(next ?? exp)}
            aria-labelledby="volume-label"
            // Without this a screen reader announces the raw exponent ("4")
            // instead of the volume the user is actually choosing (10,000).
            aria-valuetext={`${volume.toLocaleString()} verifications per month`}
          />

          <div className="text-muted-foreground mt-2 flex justify-between text-xs">
            <span>100</span>
            <span>10K</span>
            <span>2M</span>
          </div>
        </div>

        {/* Announce the recommendation so a keyboard user driving the slider
            hears the result change instead of only seeing it. */}
        <div className="bg-muted/50 rounded-lg p-6" aria-live="polite">
          <p className="text-muted-foreground text-xs tracking-wide uppercase">Recommended plan</p>
          <p className="mt-1 text-2xl font-semibold">{result.plan.name}</p>

          {result.monthlyCost === null ? (
            <>
              <p className="text-muted-foreground mt-4 text-sm">
                At this volume a negotiated contract beats metered overage. Let&apos;s talk about
                committed pricing and data residency.
              </p>
              <Button className="mt-5 w-full" asChild>
                <Link href="/contact?topic=enterprise">Contact sales</Link>
              </Button>
            </>
          ) : (
            <>
              <p className="mt-4 font-mono text-3xl font-semibold tabular-nums">
                {currency(result.monthlyCost)}
                <span className="text-muted-foreground ml-1.5 font-sans text-sm font-normal">
                  / month
                </span>
              </p>

              <dl className="text-muted-foreground mt-4 space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <dt>Base</dt>
                  <dd className="font-mono tabular-nums">{currency(result.plan.price ?? 0)}</dd>
                </div>
                {result.overageUnits > 0 ? (
                  <div className="flex justify-between">
                    <dt>
                      Overage · {result.overageUnits.toLocaleString()} ×{" "}
                      {currency(result.plan.overage ?? 0)}
                    </dt>
                    <dd className="font-mono tabular-nums">{currency(result.overageCost)}</dd>
                  </div>
                ) : (
                  <div className="flex justify-between">
                    <dt>Included</dt>
                    <dd className="font-mono tabular-nums">
                      {result.plan.verifications?.toLocaleString()}
                    </dd>
                  </div>
                )}
                <div className="flex justify-between border-t pt-1.5">
                  <dt>Cost per verification</dt>
                  <dd className="font-mono tabular-nums">
                    ${(result.monthlyCost / volume).toFixed(4)}
                  </dd>
                </div>
              </dl>

              <Button className="mt-5 w-full" asChild>
                <Link href={result.plan.cta.href}>{result.plan.cta.label}</Link>
              </Button>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}
