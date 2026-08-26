import type { Metadata } from "next";

import { DocsPager } from "@/components/docs/docs-pager";
import { DocsSidebar } from "@/components/docs/docs-sidebar";

export const metadata: Metadata = {
  title: { default: "Documentation", template: "%s · Fvas Docs" },
};

/**
 * Docs shell: persistent sidebar beside a constrained prose column.
 *
 * The column is capped near 70 characters — long measures are the single most
 * common readability failure in developer documentation.
 */
export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl gap-12 px-6 py-10 lg:grid lg:grid-cols-[220px_1fr] lg:py-14">
      <aside className="hidden lg:block">
        <div className="sticky top-24 max-h-[calc(100dvh-8rem)] overflow-y-auto pb-8">
          <DocsSidebar />
        </div>
      </aside>

      <div className="min-w-0">
        {/* On narrow screens the sidebar becomes an inline index above the
            content rather than a hidden drawer — a docs reader needs to see
            what else exists. */}
        <details className="mb-8 rounded-lg border p-4 lg:hidden">
          <summary className="cursor-pointer text-sm font-medium">Documentation index</summary>
          <div className="mt-4">
            <DocsSidebar />
          </div>
        </details>

        <article className="max-w-[68ch]">{children}</article>
        <div className="max-w-[68ch]">
          <DocsPager />
        </div>
      </div>
    </div>
  );
}
