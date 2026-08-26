import * as React from "react";

import { CodeBlock } from "@/components/code-block";

/**
 * MDX emits ```lang fences as <pre><code className="language-lang">…</code></pre>.
 * This intercepts that shape and routes it through the same Shiki CodeBlock the
 * marketing pages use, so docs and landing code look identical.
 *
 * Async server component: highlighting happens during render, never in the
 * browser.
 */
export async function MdxPre({ children }: { children?: React.ReactNode }) {
  const child = React.isValidElement<{ className?: string; children?: React.ReactNode }>(children)
    ? children
    : null;

  const code = typeof child?.props.children === "string" ? child.props.children : "";
  const lang = child?.props.className?.replace("language-", "") ?? "text";

  // A fence we cannot parse still has to render something readable rather than
  // silently disappearing.
  if (!code) {
    return (
      <pre className="bg-card mt-6 overflow-x-auto rounded-lg border p-4 text-[13px]">
        {children}
      </pre>
    );
  }

  return <CodeBlock code={code} lang={lang} className="mt-6" />;
}

/** Inline `code` — the block case is handled by MdxPre above. */
export function MdxCode({ className, children, ...props }: React.ComponentProps<"code">) {
  // A <code> carrying a language class is inside a fence; MdxPre already
  // consumed it, so pass it straight through unstyled.
  if (className?.startsWith("language-")) {
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  }

  return (
    <code
      className="bg-muted text-foreground rounded px-[0.35em] py-[0.15em] font-mono text-[0.875em]"
      {...props}
    >
      {children}
    </code>
  );
}
