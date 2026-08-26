import Link from "next/link";
import { TriangleAlert } from "lucide-react";

const LEGAL_PAGES = [
  { title: "Privacy Policy", href: "/legal/privacy" },
  { title: "Terms of Service", href: "/legal/terms" },
  { title: "Data Processing Addendum", href: "/legal/dpa" },
];

export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-3xl px-6 py-12 sm:py-16">
      <nav aria-label="Legal documents" className="flex flex-wrap gap-2">
        {LEGAL_PAGES.map((page) => (
          <Link
            key={page.href}
            href={page.href}
            className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring rounded-md border px-3 py-1.5 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
          >
            {page.title}
          </Link>
        ))}
      </nav>

      {/* Presenting an unreviewed template as a binding policy would be
          misleading, and a prospect's counsel will spot it immediately. Saying
          so plainly costs nothing and is the only defensible option. */}
      <div className="border-warning/30 bg-warning/5 mt-8 flex gap-3 rounded-lg border p-4">
        <TriangleAlert className="text-warning mt-0.5 size-4 shrink-0" aria-hidden />
        <p className="text-muted-foreground text-sm leading-relaxed">
          <strong className="text-foreground">Draft, not legal advice.</strong> Fvas is a pre-launch
          product and these documents are working drafts written to describe how the system actually
          behaves. They have not been reviewed by counsel and are not a binding agreement. Before
          relying on them, have your own lawyer review them against your jurisdiction and use case.
        </p>
      </div>

      <article className="mt-10">{children}</article>
    </div>
  );
}
