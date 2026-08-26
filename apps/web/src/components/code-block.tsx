import { codeToHtml } from "shiki";

import { CopyButton } from "@/components/copy-button";
import { cn } from "@/lib/utils";

/**
 * Syntax highlighting at build time, in a server component.
 *
 * Shiki runs during rendering and emits plain HTML, so the client ships zero
 * bytes of highlighter — the alternative (Prism/highlight.js in the browser)
 * costs 30–90 KB of JS and produces a visible flash of unstyled code, both of
 * which we would pay for on the most performance-sensitive page we own.
 *
 * `defaultColor: false` emits both themes as CSS custom properties on every
 * token so light/dark switches instantly, with no re-highlight and no second
 * copy of the markup.
 */
export async function CodeBlock({
  code,
  lang = "bash",
  filename,
  copyable = true,
  className,
}: {
  code: string;
  lang?: string;
  filename?: string;
  copyable?: boolean;
  className?: string;
}) {
  const trimmed = code.trim();

  const html = await codeToHtml(trimmed, {
    lang,
    themes: { light: "github-light", dark: "github-dark" },
    defaultColor: false,
  });

  return (
    <div className={cn("group bg-card relative overflow-hidden rounded-lg border", className)}>
      {filename ? (
        <div className="text-muted-foreground flex items-center justify-between border-b px-4 py-2">
          <span className="font-mono text-xs">{filename}</span>
        </div>
      ) : null}

      <div className="relative">
        <div
          className="overflow-x-auto p-4 text-[13px] leading-relaxed [&_code]:font-mono [&_pre]:!bg-transparent"
          // Shiki output is generated from our own literal source strings at
          // build time — never from user input.
          dangerouslySetInnerHTML={{ __html: html }}
        />
        {copyable ? (
          <div className="absolute top-2 right-2 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <CopyButton value={trimmed} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
