import "./globals.css";
import "./console.css";

import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

export const metadata: Metadata = {
  metadataBase: new URL("https://deja-khaki.vercel.app"),
  title: "Deja | Incident Memory",
  description: "Durable execution, recalled precedent, and better incident response.",
  alternates: {
    canonical: "/",
  },
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
  },
  openGraph: {
    type: "website",
    url: "/",
    siteName: "Deja",
    title: "Deja | Incident Memory",
    description: "Durable execution, recalled precedent, and better incident response.",
    images: [
      {
        url: "/deja-og.png",
        width: 1200,
        height: 630,
        alt: "Deja incident memory",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Deja | Incident Memory",
    description: "Durable execution, recalled precedent, and better incident response.",
    images: ["/deja-og.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
