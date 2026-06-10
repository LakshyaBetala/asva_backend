import "./globals.css";
import { Hanken_Grotesk, Bricolage_Grotesque } from "next/font/google";
import { Toaster } from "@/components/ui/sonner";

// Distinctive, non-generic pairing: Hanken Grotesk (clean, warm UI body, great
// at dense data sizes) + Bricolage Grotesque (characterful display/wordmark).
// Loaded as CSS variables so Tailwind's font-sans / font-display resolve to them.
const sans = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});
const display = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
  display: "swap",
});

export const metadata = {
  title: "Almmatix Voice — CRM",
  description: "Outbound AI voice agent + lead CRM for real-estate teams",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable}`}>
      <body className="min-h-screen bg-background text-foreground antialiased">
        {children}
        <Toaster richColors position="top-right" />
      </body>
    </html>
  );
}
