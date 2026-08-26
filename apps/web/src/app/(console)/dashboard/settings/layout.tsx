"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PageHeader } from "@/components/console/page-header";
import { settingsTabs } from "@/config/console-nav";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const permissions = useAuthStore((state) => state.permissions);

  const tabs = settingsTabs.filter(
    (tab) => !tab.permission || permissions.includes(tab.permission),
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Organization configuration, members, and your own account."
      />

      {/* Real links, not client-side tab state: each settings section is its
          own URL, so it is bookmarkable and the back button works. */}
      <nav aria-label="Settings sections" className="border-b">
        <ul className="-mb-px flex gap-1 overflow-x-auto">
          {tabs.map((tab) => {
            const active = pathname === tab.href;
            return (
              <li key={tab.href}>
                <Link
                  href={tab.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "focus-visible:ring-ring inline-block border-b-2 px-3 py-2 text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none",
                    active
                      ? "border-primary text-foreground font-medium"
                      : "text-muted-foreground hover:text-foreground border-transparent",
                  )}
                >
                  {tab.title}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="max-w-3xl">{children}</div>
    </div>
  );
}
