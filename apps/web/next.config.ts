import createMDX from "@next/mdx";
import rehypeAutolinkHeadings from "rehype-autolink-headings";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  pageExtensions: ["ts", "tsx", "md", "mdx"],

  // Emit a minimal self-contained server for the Docker image. Vercel builds
  // from source and ignores this; it exists for container parity and
  // self-hosted deploys.
  output: "standalone",

  // Trace from the monorepo root so the standalone bundle picks up workspace
  // packages instead of silently omitting them.
  outputFileTracingRoot: new URL("../../", import.meta.url).pathname,

  eslint: {
    // Lint is a separate CI job. Running it inside `next build` doubles the
    // work and makes a lint failure look like a build failure.
    ignoreDuringBuilds: true,
  },

  typescript: {
    // Type errors must fail the build. Never set this to true.
    ignoreBuildErrors: false,
  },

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // The console needs the camera; nothing here needs a microphone or
          // location. Being explicit about what a biometric product does not
          // access is a trust signal, not boilerplate.
          {
            key: "Permissions-Policy",
            value: "camera=(self), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

const withMDX = createMDX({
  options: {
    remarkPlugins: [remarkGfm],
    rehypePlugins: [
      rehypeSlug,
      // Heading anchors make a docs page linkable at section granularity, which
      // is how support answers get shared.
      [rehypeAutolinkHeadings, { behavior: "wrap", properties: { className: "heading-anchor" } }],
    ],
  },
});

export default withMDX(nextConfig);
