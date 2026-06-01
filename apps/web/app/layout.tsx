import "./globals.css";
import { Toaster } from "@/components/ui/sonner";

export const metadata = {
  title: "AI Voice — SPC",
  description: "Outbound voice agent CRM",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background text-foreground antialiased">
        {children}
        <Toaster richColors position="top-right" />
      </body>
    </html>
  );
}
