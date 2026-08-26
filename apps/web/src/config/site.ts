/**
 * Single source of truth for site identity and navigation.
 *
 * Nav lives here rather than inline in the header so the same structure feeds
 * the desktop nav, the mobile sheet, the footer, and the sitemap. Four copies
 * of a link list drift within a week.
 */

export const siteConfig = {
  name: "Fvas",
  tagline: "Face Authentication Platform",
  description:
    "Add face authentication to any application with three API calls. Enroll a subject, verify in under a second, and get an audit trail your compliance team will accept.",
  url: process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000",
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  email: "hello@fvas.io",
  security: "security@fvas.io",
} as const;

export interface NavItem {
  title: string;
  href: string;
  description?: string;
  external?: boolean;
}

export const mainNav: NavItem[] = [
  { title: "Features", href: "/features" },
  { title: "Use cases", href: "/use-cases" },
  { title: "Pricing", href: "/pricing" },
  { title: "Docs", href: "/docs" },
  { title: "Changelog", href: "/changelog" },
];

export const footerNav: { title: string; items: NavItem[] }[] = [
  {
    title: "Product",
    items: [
      { title: "Features", href: "/features" },
      { title: "Use cases", href: "/use-cases" },
      { title: "Pricing", href: "/pricing" },
      { title: "Changelog", href: "/changelog" },
    ],
  },
  {
    title: "Developers",
    items: [
      { title: "Documentation", href: "/docs" },
      { title: "Quickstart", href: "/docs/quickstart" },
      { title: "API reference", href: "/docs/api-reference" },
      { title: "Errors", href: "/docs/errors" },
    ],
  },
  {
    title: "Company",
    items: [
      { title: "Contact", href: "/contact" },
      { title: "FAQ", href: "/faq" },
    ],
  },
  {
    title: "Legal",
    items: [
      { title: "Privacy", href: "/legal/privacy" },
      { title: "Terms", href: "/legal/terms" },
      { title: "DPA", href: "/legal/dpa" },
    ],
  },
];
