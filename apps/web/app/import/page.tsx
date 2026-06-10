import { requireTenant } from "@/lib/auth";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { fetchBillingSummary } from "@/lib/billing";
import { NavBar } from "@/components/NavBar";
import { CsvUploadDialog } from "@/components/CsvUpload";
import { ManualLeadDialog } from "@/components/ManualLeadDialog";
import { Download } from "lucide-react";

const COLUMNS: { col: string; required: boolean; maps: string; example: string }[] = [
  { col: "name", required: true, maps: "Client name (used in the call)", example: "Rajesh Kumar" },
  { col: "phone", required: true, maps: "Call number — +91 or 10-digit", example: "+919876543210" },
  { col: "company", required: false, maps: "Company / builder", example: "Prestige" },
  { col: "industry", required: false, maps: "Vertical", example: "real_estate" },
  { col: "source", required: false, maps: "Where it came from", example: "magicbricks" },
  { col: "notes", required: false, maps: "Context / short description", example: "Wants 2 BHK Adyar" },
];

export default async function ImportPage() {
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
        <header className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">Import leads</h1>
            <p className="mt-1.5 max-w-2xl text-muted-foreground">
              Upload a CSV (export your Excel as CSV) with your contacts. Almmatix dials them,
              qualifies, and books site visits — results land in{" "}
              <span className="font-medium text-foreground">Leads</span>.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <a
              href="/leads-sample.csv"
              download
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-input bg-background px-3 text-sm font-medium transition-colors hover:bg-accent"
            >
              <Download className="h-4 w-4" /> Sample CSV
            </a>
            <ManualLeadDialog />
            <CsvUploadDialog />
          </div>
        </header>

        {/* Format spec */}
        <section className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
          <div className="border-b border-border px-6 py-4">
            <h2 className="font-display text-lg font-semibold">CSV format</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              First row must be the header. <span className="font-medium text-foreground">name</span> and{" "}
              <span className="font-medium text-foreground">phone</span> are required; the rest are optional.
              Max 10,000 rows, UTF-8.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-6 py-2.5 font-medium">Column</th>
                  <th className="px-6 py-2.5 font-medium">Required</th>
                  <th className="px-6 py-2.5 font-medium">What it&apos;s for</th>
                  <th className="px-6 py-2.5 font-medium">Example</th>
                </tr>
              </thead>
              <tbody>
                {COLUMNS.map((c) => (
                  <tr key={c.col} className="border-t border-border/70">
                    <td className="px-6 py-2.5">
                      <code className="rounded bg-muted px-1.5 py-0.5 font-medium">{c.col}</code>
                    </td>
                    <td className="px-6 py-2.5">
                      {c.required ? (
                        <span className="rounded-full bg-brand/10 px-2 py-0.5 text-xs font-medium text-brand">
                          Required
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">Optional</span>
                      )}
                    </td>
                    <td className="px-6 py-2.5 text-muted-foreground">{c.maps}</td>
                    <td className="px-6 py-2.5">
                      <span className="tabular text-muted-foreground">{c.example}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Language note */}
        <section className="rounded-xl border border-border bg-accent/40 p-5 text-sm text-accent-foreground">
          <p>
            <span className="font-semibold">Call language:</span> Hindi, English, or Tamil — chosen
            when you launch a call (per campaign / per lead). The agent auto-detects and switches mid-call
            too, so a Hindi lead who replies in Tamil is handled seamlessly. A per-row{" "}
            <code className="rounded bg-background/60 px-1 py-0.5">language</code> column is on the way.
          </p>
        </section>
      </main>
    </>
  );
}
