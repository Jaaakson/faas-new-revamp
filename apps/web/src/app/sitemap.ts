import type { MetadataRoute } from "next";

import { allDocs } from "@/config/docs";
import { siteConfig } from "@/config/site";
import { useCases } from "@/lib/content/use-cases";

/**
 * Sitemap generated from the same config the navigation uses.
 *
 * A hand-maintained list of URLs is wrong within two releases. Deriving it means
 * a new use case or docs page is indexed the moment it is linked.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const base = siteConfig.url;
  const now = new Date();

  const primary = [
    { path: "", priority: 1.0, changeFrequency: "weekly" as const },
    { path: "/features", priority: 0.9, changeFrequency: "monthly" as const },
    { path: "/pricing", priority: 0.9, changeFrequency: "monthly" as const },
    { path: "/use-cases", priority: 0.8, changeFrequency: "monthly" as const },
    { path: "/faq", priority: 0.7, changeFrequency: "monthly" as const },
    { path: "/changelog", priority: 0.6, changeFrequency: "weekly" as const },
    { path: "/contact", priority: 0.5, changeFrequency: "yearly" as const },
  ];

  const legal = ["/legal/privacy", "/legal/terms", "/legal/dpa"];

  return [
    ...primary.map((entry) => ({
      url: `${base}${entry.path}`,
      lastModified: now,
      changeFrequency: entry.changeFrequency,
      priority: entry.priority,
    })),
    ...useCases.map((useCase) => ({
      url: `${base}/use-cases/${useCase.slug}`,
      lastModified: now,
      changeFrequency: "monthly" as const,
      priority: 0.7,
    })),
    ...allDocs.map((doc) => ({
      url: `${base}${doc.href}`,
      lastModified: now,
      changeFrequency: "weekly" as const,
      // Docs rank well and convert developers; they are not an afterthought.
      priority: doc.href === "/docs/quickstart" ? 0.9 : 0.8,
    })),
    ...legal.map((path) => ({
      url: `${base}${path}`,
      lastModified: now,
      changeFrequency: "yearly" as const,
      priority: 0.3,
    })),
  ];
}
