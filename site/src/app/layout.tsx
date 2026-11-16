import type { Metadata, Viewport } from "next";
import { Chakra_Petch, Hanken_Grotesk, Kode_Mono } from "next/font/google";
import { themeScript } from "@/components/ThemeToggle";
import { SITE_URL } from "@/lib/site";
import "./globals.css";

const display = Chakra_Petch({ variable: "--font-display", subsets: ["latin"], weight: ["500", "600", "700"] });
const body = Hanken_Grotesk({ variable: "--font-body", subsets: ["latin"] });
const mono = Kode_Mono({ variable: "--font-mono", subsets: ["latin"] });

const description =
  "A Claude Code plugin for macOS: Claude starts a Google Meet, a voice agent asks the person your questions, and Claude answers code questions mid-call.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "VoyVoy: let Claude Code call people",
  description,
  openGraph: {
    title: "VoyVoy: let Claude Code call people",
    description,
    url: SITE_URL,
    siteName: "VoyVoy",
    type: "website",
    images: [{ url: "/og.png", width: 2400, height: 1260, alt: "VoyVoy: let Claude Code call people, on Google Meet" }],
  },
  twitter: { card: "summary_large_image", title: "VoyVoy: let Claude Code call people", description, images: ["/og.png"] },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f8fa" },
    { media: "(prefers-color-scheme: dark)", color: "#0e1014" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
