import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "K+ Research",
  description: "AI-powered equity research platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="kp-noise min-h-screen bg-[var(--kp-void)]">
        {children}
      </body>
    </html>
  );
}
