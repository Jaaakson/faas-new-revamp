import Link from "next/link";

import { Logo } from "@/components/marketing/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { footerNav, siteConfig } from "@/config/site";

export function SiteFooter() {
  return (
    <footer className="border-t">
      <div className="mx-auto max-w-6xl px-6 py-12">
        <div className="grid gap-10 md:grid-cols-[1.5fr_repeat(4,1fr)]">
          <div>
            <Logo />
            <p className="text-muted-foreground mt-3 max-w-xs text-sm">
              Face authentication as an API. Built for teams that need a real identity factor, not
              another password.
            </p>
          </div>

          {footerNav.map((group) => (
            <div key={group.title}>
              <h2 className="text-xs font-medium tracking-wide uppercase">{group.title}</h2>
              <ul className="mt-3 space-y-2">
                {group.items.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className="text-muted-foreground hover:text-foreground focus-visible:ring-ring rounded text-sm transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                    >
                      {item.title}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="text-muted-foreground mt-12 flex flex-col gap-4 border-t pt-6 text-sm sm:flex-row sm:items-center sm:justify-between">
          <p>
            © {new Date().getFullYear()} {siteConfig.name}. MIT licensed.
          </p>
          <div className="flex items-center gap-4">
            {/* Stated plainly rather than implied: the MVP does not ship
                certified liveness, and the marketing surface says so. */}
            <span className="text-xs">Not certified for ISO 30107-3 PAD</span>
            <ThemeToggle />
          </div>
        </div>
      </div>
    </footer>
  );
}
