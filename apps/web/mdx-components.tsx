import type { MDXComponents } from "mdx/types";

import {
  CreateSubjectSample,
  EnrollSample,
  VerifySample,
  WebhookVerifySample,
} from "@/components/docs/api-samples";
import { Callout } from "@/components/docs/callout";
import { CodeTabs } from "@/components/docs/code-tabs";
import { MdxCode, MdxPre } from "@/components/docs/mdx-code";

/**
 * Element mapping for every MDX file.
 *
 * Markdown ships no styling, so this is where docs content inherits the design
 * system. Defining it once here — rather than per page — is what keeps a
 * fifteen-page docs site visually identical to the rest of the product.
 */
export function useMDXComponents(components: MDXComponents): MDXComponents {
  return {
    h1: (props) => (
      <h1 className="mt-2 scroll-m-20 text-3xl font-semibold tracking-tight" {...props} />
    ),
    h2: (props) => (
      <h2
        className="mt-12 scroll-m-20 border-t pt-8 text-2xl font-semibold tracking-tight first:mt-0 first:border-0 first:pt-0"
        {...props}
      />
    ),
    h3: (props) => (
      <h3 className="mt-8 scroll-m-20 text-lg font-semibold tracking-tight" {...props} />
    ),
    h4: (props) => (
      <h4 className="mt-6 scroll-m-20 text-base font-semibold tracking-tight" {...props} />
    ),
    p: (props) => <p className="text-muted-foreground mt-4 leading-7" {...props} />,
    ul: (props) => (
      <ul className="text-muted-foreground mt-4 ml-6 list-disc space-y-2" {...props} />
    ),
    ol: (props) => (
      <ol className="text-muted-foreground mt-4 ml-6 list-decimal space-y-2" {...props} />
    ),
    li: (props) => <li className="leading-7" {...props} />,
    a: (props) => (
      <a
        className="text-primary font-medium underline underline-offset-4 hover:no-underline"
        {...props}
      />
    ),
    strong: (props) => <strong className="text-foreground font-semibold" {...props} />,
    blockquote: (props) => (
      <blockquote
        className="text-muted-foreground border-primary mt-6 border-l-2 pl-6 italic"
        {...props}
      />
    ),
    hr: () => <hr className="my-10" />,
    table: (props) => (
      // Wide tables scroll inside their own container; the page body must never
      // scroll horizontally.
      <div className="mt-6 w-full overflow-x-auto">
        <table className="w-full text-sm" {...props} />
      </div>
    ),
    th: (props) => (
      <th
        className="border-b px-3 py-2 text-left text-xs font-medium tracking-wide uppercase"
        {...props}
      />
    ),
    td: (props) => (
      <td className="text-muted-foreground border-b px-3 py-2 align-top" {...props} />
    ),
    pre: MdxPre,
    code: MdxCode,
    Callout,
    CodeTabs,
    CreateSubjectSample,
    EnrollSample,
    VerifySample,
    WebhookVerifySample,
    ...components,
  };
}
