import Link from "next/link";
import { CircleCheck, ScanFace } from "lucide-react";

/**
 * Split auth layout: form left, product truth right.
 *
 * The right panel shows an actual verification decision rather than a stock
 * photo — the same reasoning as the landing hero. On mobile it collapses to a
 * logo lockup, because a decorative panel above the fold just pushes the form
 * off screen.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <div className="flex flex-col px-6 py-8 sm:px-12">
        <Link
          href="/"
          className="focus-visible:ring-ring inline-flex w-fit items-center gap-2 rounded-md focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          <ScanFace className="text-primary size-5" aria-hidden />
          <span className="font-semibold tracking-tight">Fvas</span>
        </Link>

        <main id="main" className="flex flex-1 items-center justify-center py-12">
          <div className="w-full max-w-[400px]">{children}</div>
        </main>

        <p className="text-muted-foreground text-xs">
          By continuing you agree to our{" "}
          <Link href="/legal/terms" className="underline underline-offset-4">
            Terms
          </Link>{" "}
          and{" "}
          <Link href="/legal/privacy" className="underline underline-offset-4">
            Privacy Policy
          </Link>
          .
        </p>
      </div>

      <aside
        className="bg-muted/40 hidden flex-col justify-center border-l px-12 lg:flex"
        aria-hidden
      >
        <blockquote className="max-w-md">
          <p className="text-2xl font-medium tracking-tight">
            &ldquo;A password proves someone has credentials. It does not prove who is holding the
            phone.&rdquo;
          </p>
        </blockquote>

        <div className="bg-card mt-10 max-w-md rounded-xl border p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-success flex items-center gap-2 text-sm font-semibold tracking-wide uppercase">
              <CircleCheck className="size-4" /> Verified
            </span>
            <code className="text-muted-foreground font-mono text-xs">vs_01HQZX8K…</code>
          </div>
          <div className="mt-4">
            <div className="text-muted-foreground flex items-baseline justify-between text-xs">
              <span>Similarity</span>
              <span className="text-foreground font-mono text-lg tabular-nums">0.8121</span>
            </div>
            <div className="bg-muted relative mt-2 h-2 rounded-full">
              <div className="bg-success h-full rounded-full" style={{ width: "81.21%" }} />
              <div className="bg-foreground absolute -top-1 h-4 w-px" style={{ left: "38%" }} />
            </div>
            <div className="text-muted-foreground mt-2 flex justify-between text-[11px]">
              <span>0.0</span>
              <span className="font-mono">threshold 0.38</span>
              <span>1.0</span>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
