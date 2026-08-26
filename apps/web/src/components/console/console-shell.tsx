"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronsLeft,
  ChevronsRight,
  LogOut,
  Menu,
  ScanFace,
  Search,
  Settings,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { CommandPalette } from "@/components/console/command-palette";
import { OrgSwitcher } from "@/components/console/org-switcher";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { consoleNav, settingsNav } from "@/config/console-nav";
import { api, bffFetch } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";

interface Usage {
  plan: string;
  used: number;
  limit: number | null;
  percentage: number;
  days_remaining: number;
}

export function ConsoleShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const clear = useAuthStore((state) => state.clear);
  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);

  // Persisted so the choice survives a reload — a preference that resets every
  // navigation is worse than not offering it.
  React.useEffect(() => {
    setCollapsed(localStorage.getItem("fvas:sidebar") === "collapsed");
  }, []);

  function toggleCollapsed() {
    setCollapsed((current) => {
      localStorage.setItem("fvas:sidebar", current ? "expanded" : "collapsed");
      return !current;
    });
  }

  const signOut = React.useCallback(async () => {
    try {
      await bffFetch("/api/auth/logout");
    } finally {
      queryClient.clear();
      clear();
      toast.success("Signed out.");
      router.replace("/login");
    }
  }, [queryClient, clear, router]);

  return (
    <div className="flex min-h-dvh">
      <CommandPalette onSignOut={() => void signOut()} />

      {/*
        `sticky top-0 h-dvh` is load-bearing, not decoration.

        Without it the aside is an ordinary flex child of a `min-h-dvh` row, so
        it stretches to match the *content* column. On a long page that made the
        sidebar thousands of pixels tall and pushed the quota meter and collapse
        control to the bottom of the document — they visibly drifted downward as
        data loaded and the page grew.

        Pinning the aside to the viewport gives it a fixed height regardless of
        what the content column does. `SidebarNav` already carries
        `flex-1 overflow-y-auto`, so a long nav scrolls inside the sidebar and
        the footer stays anchored to the bottom of the screen.
      */}
      <aside
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 border-r md:flex md:flex-col",
          // Width animates; height must not, or a collapse would re-trigger
          // the layout shift this fix exists to prevent.
          "transition-[width] duration-200 ease-out motion-reduce:transition-none",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div className="flex h-14 items-center gap-2 border-b px-3">
          <Link
            href="/dashboard"
            className="focus-visible:ring-ring flex items-center gap-2 rounded-md focus-visible:ring-2 focus-visible:outline-none"
          >
            <ScanFace className="text-primary size-5 shrink-0" aria-hidden />
            {!collapsed ? <span className="font-semibold tracking-tight">Fvas</span> : null}
          </Link>
        </div>

        <div className="border-b p-2">
          <OrgSwitcher collapsed={collapsed} />
        </div>

        <SidebarNav collapsed={collapsed} />

        <div className="mt-auto border-t p-2">
          {!collapsed ? <QuotaMeter /> : null}
          <div className="mt-2 flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleCollapsed}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {collapsed ? <ChevronsRight /> : <ChevronsLeft />}
            </Button>
            {!collapsed ? <ThemeToggle /> : null}
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="bg-background/80 sticky top-0 z-40 flex h-14 items-center gap-3 border-b px-4 backdrop-blur-md sm:px-6">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
                <Menu />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64 p-0">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <div className="border-b p-3">
                <OrgSwitcher />
              </div>
              <SidebarNav collapsed={false} onNavigate={() => setMobileOpen(false)} />
              <div className="border-t p-3">
                <QuotaMeter />
              </div>
            </SheetContent>
          </Sheet>

          <button
            type="button"
            // Dispatching the real shortcut keeps one implementation of "open
            // the palette" rather than lifting its state into the shell.
            onClick={() =>
              document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))
            }
            className="text-muted-foreground hover:bg-accent focus-visible:ring-ring flex h-8 max-w-64 flex-1 items-center gap-2 rounded-md border px-2.5 text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none"
          >
            <Search className="size-3.5" aria-hidden />
            <span>Search…</span>
            <kbd className="bg-muted ml-auto rounded px-1.5 py-0.5 font-mono text-[10px]">⌘K</kbd>
          </button>

          <div className="ml-auto flex items-center gap-1">
            <div className="md:hidden">
              <ThemeToggle />
            </div>
            <UserMenu onSignOut={() => void signOut()} />
          </div>
        </header>

        <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}

function SidebarNav({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const permissions = useAuthStore((state) => state.permissions);

  const isActive = (href: string) =>
    href === "/dashboard" ? pathname === href : pathname.startsWith(href);

  return (
    <nav aria-label="Console" className="flex-1 overflow-y-auto p-2">
      {consoleNav.map((group) => {
        const items = group.items.filter(
          (item) => !item.permission || permissions.includes(item.permission),
        );
        // A group whose every item is hidden by permission renders as a bare
        // heading otherwise — visual debris that tells the user nothing.
        if (items.length === 0) return null;

        return (
          <div key={group.title} className="mb-4">
            {!collapsed ? (
              <p className="text-muted-foreground mb-1 px-2 text-[11px] font-medium tracking-wide uppercase">
                {group.title}
              </p>
            ) : null}
            <ul className="space-y-0.5">
              {items.map((item) => (
                <li key={item.href}>
                  <Link
                    href={item.comingSoon ? "#" : item.href}
                    onClick={(event) => {
                      if (item.comingSoon) event.preventDefault();
                      else onNavigate?.();
                    }}
                    aria-current={isActive(item.href) ? "page" : undefined}
                    aria-disabled={item.comingSoon || undefined}
                    title={collapsed ? item.title : undefined}
                    className={cn(
                      "focus-visible:ring-ring flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none",
                      collapsed && "justify-center",
                      item.comingSoon
                        ? "text-muted-foreground/50 cursor-not-allowed"
                        : isActive(item.href)
                          ? "bg-accent text-foreground font-medium"
                          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                    )}
                  >
                    <item.icon className="size-4 shrink-0" aria-hidden />
                    {!collapsed ? (
                      <>
                        <span className="flex-1 truncate">{item.title}</span>
                        {item.comingSoon ? <span className="text-[10px]">soon</span> : null}
                      </>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        );
      })}

      <div className="border-t pt-2">
        <Link
          href={settingsNav.href}
          onClick={onNavigate}
          aria-current={isActive(settingsNav.href) ? "page" : undefined}
          title={collapsed ? settingsNav.title : undefined}
          className={cn(
            "focus-visible:ring-ring flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none",
            collapsed && "justify-center",
            isActive(settingsNav.href)
              ? "bg-accent text-foreground font-medium"
              : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
          )}
        >
          <Settings className="size-4 shrink-0" aria-hidden />
          {!collapsed ? settingsNav.title : null}
        </Link>
      </div>
    </nav>
  );
}

/**
 * Quota consumption, pinned to the sidebar footer.
 *
 * A paid-conversion surface disguised as a utility — and it belongs where the
 * user already looks rather than behind a billing tab they never open.
 */
function QuotaMeter() {
  const organizationId = useAuthStore((state) => state.organization?.id);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.usage(organizationId ?? ""),
    queryFn: () => api.get<Usage>("/v1/console/usage/current"),
    enabled: !!organizationId,
  });

  if (isLoading) {
    return (
      <div className="px-2 py-1">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="mt-2 h-1.5 w-full" />
      </div>
    );
  }
  if (!data) return null;

  const unlimited = data.limit === null;
  const pct = Math.min(100, data.percentage);
  const tone = pct >= 100 ? "bg-destructive" : pct >= 80 ? "bg-warning" : "bg-primary";

  return (
    <div className="px-2 py-1">
      <div className="flex items-center justify-between text-xs">
        <Badge variant="secondary" className="capitalize">
          {data.plan}
        </Badge>
        <span className="text-muted-foreground tabular-nums">
          {unlimited
            ? "unlimited"
            : `${data.used.toLocaleString()} / ${data.limit?.toLocaleString()}`}
        </span>
      </div>
      {!unlimited ? (
        <>
          <div className="bg-muted mt-2 h-1.5 overflow-hidden rounded-full">
            <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
          </div>
          <p className="text-muted-foreground mt-1 text-[11px]">
            Resets in {data.days_remaining} day{data.days_remaining === 1 ? "" : "s"}
          </p>
        </>
      ) : null}
    </div>
  );
}

function UserMenu({ onSignOut }: { onSignOut: () => void }) {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const organization = useAuthStore((state) => state.organization);

  const initials = (user?.full_name ?? user?.email ?? "?")
    .split(" ")
    .map((part) => part.charAt(0))
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="focus-visible:ring-ring bg-muted flex size-8 items-center justify-center rounded-full text-xs font-medium focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
        aria-label="Account menu"
      >
        {initials}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <p className="text-sm font-medium">{user?.full_name ?? "—"}</p>
          <p className="text-muted-foreground truncate text-xs">{user?.email}</p>
          {organization ? (
            <Badge variant="outline" className="mt-2">
              {organization.role}
            </Badge>
          ) : null}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/dashboard/settings/profile")}>
          <UserRound />
          Profile
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => router.push("/dashboard/settings")}>
          <Settings />
          Settings
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={onSignOut}>
          <LogOut />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
