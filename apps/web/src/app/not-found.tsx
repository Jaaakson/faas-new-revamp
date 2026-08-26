import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { Logo } from "@/components/marketing/logo";
import { Button } from "@/components/ui/button";

/**
 * 404. Lives at the app root so it covers every route group, including the
 * console once that exists.
 */
export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-6 text-center">
      <Logo />
      <p className="text-muted-foreground mt-10 font-mono text-sm">404</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">This page doesn&apos;t exist.</h1>
      <p className="text-muted-foreground mt-3 max-w-md">
        The link may be out of date, or the page may have moved. The documentation and the landing
        page are both a click away.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Button asChild>
          <Link href="/">
            <ArrowLeft /> Back home
          </Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href="/docs">Read the docs</Link>
        </Button>
      </div>
    </div>
  );
}
