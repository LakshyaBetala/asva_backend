import Link from "next/link";
import { Settings } from "lucide-react";
import { signOutAction } from "@/app/login/actions";
import { UnitsRemainingWidget } from "./UnitsRemainingWidget";

// The product is intentionally 5 focused pages. Settings is a gear, not a tab.
const NAV_ITEMS = [
  { href: "/import", label: "Import" },
  { href: "/leads", label: "Leads" },
  { href: "/results", label: "Results" },
  { href: "/auto-leads", label: "Auto-Leads" },
  { href: "/credits", label: "Credits" },
];

export function NavBar({
  tenantName,
  unitsUsed,
  unitsAllowance,
  wigglePct,
}: {
  tenantName: string;
  unitsUsed?: number;
  unitsAllowance?: number;
  wigglePct?: number;
}) {
  return (
    <nav className="sticky top-0 z-30 border-b border-border/70 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
        <div className="flex items-center gap-7">
          <Link href="/leads" className="flex items-center gap-2.5">
            {/* live-call pulse — the product is real-time calling */}
            <span className="relative flex h-2.5 w-2.5" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand/50" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand" />
            </span>
            <span className="font-display text-[17px] font-semibold tracking-tight">
              Almmatix<span className="text-brand"> Voice</span>
            </span>
          </Link>
          <div className="hidden items-center gap-1 md:flex">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                {item.label}
              </Link>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2.5">
          {typeof unitsUsed === "number" && typeof unitsAllowance === "number" && (
            <UnitsRemainingWidget
              unitsUsed={unitsUsed}
              allowance={unitsAllowance}
              wigglePct={wigglePct}
            />
          )}
          {tenantName && tenantName !== "—" && (
            <span className="hidden max-w-[14ch] truncate text-sm font-medium text-muted-foreground lg:inline">
              {tenantName}
            </span>
          )}
          <Link
            href="/settings"
            aria-label="Settings"
            className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Settings className="h-4 w-4" />
          </Link>
          <form action={signOutAction}>
            <button
              type="submit"
              className="rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              Sign out
            </button>
          </form>
        </div>
      </div>
    </nav>
  );
}
