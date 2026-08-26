"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import {
  Building2,
  ChartNoAxesColumn,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Monitor,
  Moon,
  ScanFace,
  ScrollText,
  Settings,
  Sun,
  UserRound,
  UserRoundPlus,
} from "lucide-react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import { DialogTitle } from "@/components/ui/dialog";
import { useAuthStore } from "@/stores/auth-store";

/**
 * ⌘K command palette — the power-user spine of the console.
 *
 * Reaches every route and every primary action, so the whole product is
 * operable from the keyboard without learning where anything lives. Items are
 * filtered by permission: showing a Viewer a "Create API key" command that
 * 403s would be worse than not showing it.
 */
export function CommandPalette({ onSignOut }: { onSignOut: () => void }) {
  const router = useRouter();
  const { setTheme } = useTheme();
  const [open, setOpen] = React.useState(false);
  const permissions = useAuthStore((state) => state.permissions);

  React.useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((current) => !current);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const can = (permission?: string) => !permission || permissions.includes(permission);

  function run(action: () => void) {
    setOpen(false);
    // Defer so the dialog's close animation and focus restore finish before the
    // route changes — otherwise focus lands on a node that is being unmounted.
    setTimeout(action, 0);
  }

  const navigation = [
    { title: "Dashboard", icon: LayoutDashboard, href: "/dashboard" },
    {
      title: "Analytics",
      icon: ChartNoAxesColumn,
      href: "/dashboard/analytics",
      permission: "verification:read",
    },
    { title: "Subjects", icon: UserRound, href: "/dashboard/subjects", permission: "subject:read" },
    {
      title: "Verifications",
      icon: ScanFace,
      href: "/dashboard/verifications",
      permission: "verification:read",
    },
    { title: "Logs", icon: ScrollText, href: "/dashboard/logs", permission: "audit:read" },
    { title: "Settings", icon: Settings, href: "/dashboard/settings" },
  ].filter((item) => can(item.permission));

  const actions = [
    {
      title: "Invite a member",
      icon: UserRoundPlus,
      href: "/dashboard/settings/members",
      permission: "member:invite",
    },
    {
      title: "Organization settings",
      icon: Building2,
      href: "/dashboard/settings",
      permission: "settings:read",
    },
    { title: "API keys", icon: KeyRound, href: "/dashboard/api-keys", permission: "apikey:read" },
  ].filter((item) => can(item.permission));

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      {/* Radix requires an accessible title on every dialog; the input already
          describes the purpose visually, so this is screen-reader only. */}
      <DialogTitle className="sr-only">Command palette</DialogTitle>
      <CommandInput placeholder="Search or jump to…" />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>

        <CommandGroup heading="Navigate">
          {navigation.map((item) => (
            <CommandItem
              key={item.href}
              value={`navigate ${item.title}`}
              onSelect={() => run(() => router.push(item.href))}
            >
              <item.icon />
              {item.title}
            </CommandItem>
          ))}
        </CommandGroup>

        {actions.length > 0 ? (
          <CommandGroup heading="Actions">
            {actions.map((item) => (
              <CommandItem
                key={item.title}
                value={`action ${item.title}`}
                onSelect={() => run(() => router.push(item.href))}
              >
                <item.icon />
                {item.title}
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}

        <CommandGroup heading="Preferences">
          <CommandItem value="theme light" onSelect={() => run(() => setTheme("light"))}>
            <Sun />
            Light theme
          </CommandItem>
          <CommandItem value="theme dark" onSelect={() => run(() => setTheme("dark"))}>
            <Moon />
            Dark theme
          </CommandItem>
          <CommandItem value="theme system" onSelect={() => run(() => setTheme("system"))}>
            <Monitor />
            System theme
          </CommandItem>
          <CommandItem value="sign out" onSelect={() => run(onSignOut)}>
            <LogOut />
            Sign out
            <CommandShortcut>⇧⌘Q</CommandShortcut>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
