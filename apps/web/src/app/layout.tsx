import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { Providers } from "@/components/providers";

import "./globals.css";

/**
 * Fonts are self-hosted through next/font: no external request, no layout
 * shift, and no third-party origin in the CSP.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000"),
  title: {
    default: "Fvas — Face Authentication Platform",
    template: "%s · Fvas",
  },
  description:
    "Add face authentication to any application with three API calls. Enroll a subject, verify in under a second, and get an audit trail your compliance team will accept.",
  keywords: [
    "face authentication",
    "biometric verification",
    "identity verification API",
    "face recognition API",
  ],
  openGraph: {
    type: "website",
    title: "Fvas — Face Authentication Platform",
    description: "Face authentication, three API calls away.",
    siteName: "Fvas",
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#020617" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning is required by next-themes: it writes the theme
    // class on <html> before React hydrates, which is what prevents a flash of
    // the wrong theme. This is the one sanctioned use of the attribute.
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} ${jetbrainsMono.variable}`}>
        <Providers>
          <a
            href="#main"
            className="bg-primary text-primary-foreground sr-only rounded-md px-4 py-2 focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50"
          >
            Skip to content
          </a>
          {children}
        </Providers>
      </body>
    </html>
  );
}
