import { requireTenant } from "@/lib/auth";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { fetchBillingSummary } from "@/lib/billing";
import { NavBar } from "@/components/NavBar";
import { Sparkles, MapPin, Building2, Globe } from "lucide-react";

const SOURCES = [
  { icon: Building2, name: "Magicbricks & 99acres", desc: "Auto-pull fresh broker enquiries as they post." },
  { icon: MapPin, name: "Google Maps / Places", desc: "Discover owners & agents by locality and radius." },
  { icon: Globe, name: "JustDial & web forms", desc: "Capture inbound interest the moment it lands." },
];

export default async function AutoLeadsPage() {
  const { tenantId } = await requireTenant();
  const supabase = createSupabaseServerClient();
  const [{ data: tenant }, billing] = await Promise.all([
    supabase.from("tenants").select("name").eq("id", tenantId).single(),
    fetchBillingSummary(tenantId),
  ]);

  return (
    <>
      <NavBar
        tenantName={tenant?.name ?? "—"}
        unitsUsed={billing.unitsUsed}
        unitsAllowance={billing.unitsAllowance}
        wigglePct={billing.wigglePct}
      />
      <main className="mx-auto max-w-6xl space-y-8 p-6">
        <header className="flex flex-col gap-2">
          <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-brand/30 bg-brand/5 px-2.5 py-0.5 text-xs font-medium text-brand">
            <Sparkles className="h-3 w-3" /> Coming soon
          </span>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Auto lead generation</h1>
          <p className="max-w-2xl text-muted-foreground">
            Connect a source once and Almmatix keeps your pipeline full — new leads flow in,
            get dialled automatically, and land in <span className="font-medium text-foreground">Leads</span>{" "}
            already scored hot / warm / cold. No more manual CSV imports.
          </p>
        </header>

        <section className="grid gap-4 sm:grid-cols-3">
          {SOURCES.map((s) => (
            <div key={s.name} className="rounded-xl border border-border bg-card p-5 shadow-sm">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                <s.icon className="h-5 w-5" />
              </div>
              <h3 className="mt-3 font-medium">{s.name}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{s.desc}</p>
            </div>
          ))}
        </section>

        <section className="rounded-xl border border-dashed border-border bg-muted/30 p-8 text-center">
          <h2 className="font-display text-lg font-semibold">Want early access?</h2>
          <p className="mx-auto mt-1.5 max-w-md text-sm text-muted-foreground">
            Auto-generation is in build. Until then, use{" "}
            <span className="font-medium text-foreground">Import</span> to add leads in bulk —
            the calling, scoring and follow-up are already live.
          </p>
          <button
            disabled
            className="mt-5 cursor-not-allowed rounded-lg bg-primary/40 px-4 py-2 text-sm font-medium text-primary-foreground"
          >
            Notify me when it&apos;s ready
          </button>
        </section>
      </main>
    </>
  );
}
