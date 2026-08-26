import {
  ChartNoAxesColumn,
  KeyRound,
  LayoutDashboard,
  Radar,
  ScanFace,
  ScrollText,
  Settings,
  UserRound,
  Webhook,
  type LucideIcon,
} from "lucide-react";

/**
 * Console navigation.
 *
 * Grouped by *job*, not by data model: Rani the integrator lives in Developer,
 * Sari the compliance officer lives in Identity and Logs, and neither has to
 * scan a flat list of eleven items to find their half of the product
 * (docs/02-information-architecture.md §4).
 */

export interface ConsoleNavItem {
  title: string;
  href: string;
  icon: LucideIcon;
  /** Hidden when the signed-in role lacks this permission. */
  permission?: string;
  /** Present in the nav but not yet built — labelled, never a dead link. */
  comingSoon?: boolean;
}

export interface ConsoleNavGroup {
  title: string;
  items: ConsoleNavItem[];
}

export const consoleNav: ConsoleNavGroup[] = [
  {
    title: "Overview",
    items: [
      { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
      {
        title: "Analytics",
        href: "/dashboard/analytics",
        icon: ChartNoAxesColumn,
        permission: "verification:read",
      },
    ],
  },
  {
    title: "Identity",
    items: [
      {
        title: "Subjects",
        href: "/dashboard/subjects",
        icon: UserRound,
        permission: "subject:read",
      },
      {
        title: "Verifications",
        href: "/dashboard/verifications",
        icon: ScanFace,
        permission: "verification:read",
      },
      {
        title: "Live test",
        href: "/dashboard/verify",
        icon: Radar,
        permission: "verification:write",
      },
    ],
  },
  {
    title: "Developer",
    items: [
      {
        title: "API keys",
        href: "/dashboard/api-keys",
        icon: KeyRound,
        permission: "apikey:read",
      },
      {
        title: "Logs",
        href: "/dashboard/logs",
        icon: ScrollText,
        permission: "audit:read",
      },
      {
        title: "Webhooks",
        href: "/dashboard/settings/webhooks",
        icon: Webhook,
        permission: "webhook:manage",
      },
    ],
  },
];

export const settingsNav: ConsoleNavItem = {
  title: "Settings",
  href: "/dashboard/settings",
  icon: Settings,
};

export const settingsTabs = [
  { title: "General", href: "/dashboard/settings", permission: "settings:read" },
  {
    title: "Members",
    href: "/dashboard/settings/members",
    permission: "member:read",
  },
  {
    title: "Security",
    href: "/dashboard/settings/security",
    permission: "settings:read",
  },
  {
    title: "Webhooks",
    href: "/dashboard/settings/webhooks",
    permission: "webhook:manage",
  },
  { title: "Profile", href: "/dashboard/settings/profile" },
];
