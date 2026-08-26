/**
 * Documentation navigation.
 *
 * A static tree rather than a filesystem scan: ordering is editorial (quickstart
 * must come first, not alphabetically third), and a page that exists but is not
 * listed here is a deliberate draft rather than an accident.
 */

export interface DocsNavItem {
  title: string;
  href: string;
  description?: string;
}

export interface DocsNavSection {
  title: string;
  items: DocsNavItem[];
}

export const docsNav: DocsNavSection[] = [
  {
    title: "Getting started",
    items: [
      {
        title: "Introduction",
        href: "/docs",
        description: "What Fvas does, and what it deliberately does not do.",
      },
      {
        title: "Quickstart",
        href: "/docs/quickstart",
        description: "Signup to a verified response in under ten minutes.",
      },
      {
        title: "Authentication",
        href: "/docs/authentication",
        description: "API keys, environments, scopes, and rotation.",
      },
    ],
  },
  {
    title: "Core concepts",
    items: [
      {
        title: "Subjects & enrollment",
        href: "/docs/enrollment",
        description: "Register a face and understand the quality gates.",
      },
      {
        title: "Verification",
        href: "/docs/verification",
        description: "Decisions, thresholds, and confidence bands.",
      },
      {
        title: "Webhooks",
        href: "/docs/webhooks",
        description: "Event delivery, signatures, and retries.",
      },
    ],
  },
  {
    title: "Reference",
    items: [
      {
        title: "API reference",
        href: "/docs/api-reference",
        description: "Every endpoint, with request and response shapes.",
      },
      {
        title: "Errors",
        href: "/docs/errors",
        description: "The error envelope and every code you can receive.",
      },
      {
        title: "Rate limits & quotas",
        href: "/docs/rate-limits",
        description: "Two independent limits, and how to back off from each.",
      },
    ],
  },
  {
    title: "Going to production",
    items: [
      {
        title: "Best practices",
        href: "/docs/best-practices",
        description: "Where face auth belongs in your product, and where it does not.",
      },
    ],
  },
];

export const allDocs: DocsNavItem[] = docsNav.flatMap((section) => section.items);

export function docsNeighbours(pathname: string): {
  previous?: DocsNavItem;
  next?: DocsNavItem;
} {
  const index = allDocs.findIndex((item) => item.href === pathname);
  if (index === -1) return {};
  return {
    previous: index > 0 ? allDocs[index - 1] : undefined,
    next: index < allDocs.length - 1 ? allDocs[index + 1] : undefined,
  };
}
