import { SiteFooter } from "@/components/marketing/site-footer";
import { SiteHeader } from "@/components/marketing/site-header";
import { OrganizationJsonLd, SoftwareApplicationJsonLd } from "@/components/structured-data";

/**
 * Marketing shell.
 *
 * Route groups let this chrome wrap every public page without appearing in any
 * URL, and keep it entirely separate from the console shell — which shares the
 * design system but nothing else.
 */
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <OrganizationJsonLd />
      <SoftwareApplicationJsonLd />
      <SiteHeader />
      <main id="main" className="flex-1">
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
