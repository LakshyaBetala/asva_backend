import { requireTenant } from "@/lib/auth";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { fetchBillingSummary, fetchLeadCounts } from "@/lib/billing";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { updateTenantSettingsAction } from "./actions";
import { NavBar } from "@/components/NavBar";
import { PerformanceCard } from "@/components/PerformanceCard";

export default async function SettingsPage() {
  const { tenantId } = await requireTenant();
  const supabase = createSupabaseServerClient();
  const [{ data: t }, billing, leadCounts] = await Promise.all([
    supabase.from("tenants").select("*").eq("id", tenantId).single(),
    fetchBillingSummary(tenantId),
    fetchLeadCounts(tenantId),
  ]);
  if (!t) return null;

  return (
    <>
      <NavBar
        tenantName={t.name}
        unitsUsed={billing.unitsUsed}
        unitsAllowance={billing.unitsAllowance}
        wigglePct={billing.wigglePct}
      />
      <main className="mx-auto max-w-2xl space-y-6 p-6">
        <h1 className="text-2xl font-semibold">Settings — {t.name}</h1>

        <PerformanceCard
          unitsUsed={billing.unitsUsed}
          unitsAllowance={billing.unitsAllowance}
          hotCount={leadCounts.hot}
          warmCount={leadCounts.warm}
          costInr={billing.costInr}
          avgOrderSizeInr={billing.avgOrderSizeInr}
          monthlySubscriptionInr={billing.monthlySubscriptionInr}
        />
        <form
          action={async (fd: FormData) => {
            "use server";
            await updateTenantSettingsAction(fd);
          }}
          className="space-y-4"
        >
          <div>
            <Label>Persona name</Label>
            <Input name="persona_name" defaultValue={t.persona_name} />
          </div>
          <div>
            <Label>Default language</Label>
            <select
              name="persona_lang_default"
              defaultValue={t.persona_lang_default}
              className="block h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
            >
              <option value="en-IN">English (India)</option>
              <option value="hi-IN">Hindi</option>
              <option value="ta-IN">Tamil</option>
            </select>
          </div>
          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <Label className="text-base">Agent enabled</Label>
              <p className="text-xs text-muted-foreground">
                Master switch — when off, no outbound AI calls will dial.
              </p>
            </div>
            <input
              type="checkbox"
              name="agent_enabled"
              defaultChecked={t.agent_enabled !== false}
              className="h-5 w-5"
            />
          </div>

          <div>
            <Label>Telephony mode</Label>
            <select
              name="telephony_mode"
              defaultValue={t.telephony_mode ?? "managed"}
              className="block h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
            >
              <option value="managed">Managed (we provide the number)</option>
              <option value="byon">BYON (use your own Exotel/Plivo trunk)</option>
            </select>
          </div>

          <div>
            <Label>Exotel caller ID (managed mode)</Label>
            <Input
              name="exotel_caller_id"
              defaultValue={t.exotel_caller_id ?? ""}
              placeholder="+91..."
            />
          </div>

          <div className="rounded-md border border-dashed p-3 space-y-3">
            <p className="text-xs text-muted-foreground">
              BYON fields — only used when Telephony mode = BYON. Store
              credentials separately via Supabase Vault.
            </p>
            <div>
              <Label>BYON provider</Label>
              <select
                name="byon_provider"
                defaultValue={t.byon_provider ?? ""}
                className="block h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
              >
                <option value="">—</option>
                <option value="exotel">Exotel</option>
                <option value="plivo">Plivo</option>
                <option value="tata">Tata</option>
              </select>
            </div>
            <div>
              <Label>BYON from-number</Label>
              <Input
                name="byon_from_number"
                defaultValue={t.byon_from_number ?? ""}
                placeholder="+91..."
              />
            </div>
          </div>

          <div>
            <Label>WhatsApp handoff number</Label>
            <Input
              name="whatsapp_handoff_number"
              defaultValue={t.whatsapp_handoff_number ?? ""}
              placeholder="+91..."
            />
          </div>

          <div className="rounded-md border border-dashed p-3 space-y-3">
            <p className="text-xs text-muted-foreground">
              Billing &amp; cost guardrails. Defaults match the SPC pricing
              tier (₹15k/mo · 2000 units · 10% wiggle).
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Monthly unit allowance</Label>
                <Input
                  name="monthly_unit_allowance"
                  type="number"
                  min={0}
                  defaultValue={t.monthly_unit_allowance ?? 2000}
                />
              </div>
              <div>
                <Label>Wiggle room (%)</Label>
                <Input
                  name="wiggle_room_pct"
                  type="number"
                  min={0}
                  max={50}
                  defaultValue={t.wiggle_room_pct ?? 10}
                />
              </div>
              <div>
                <Label>Overage rate (₹/unit)</Label>
                <Input
                  name="overage_rate_inr"
                  type="number"
                  min={0}
                  step={0.01}
                  defaultValue={t.overage_rate_inr ?? 10}
                />
              </div>
              <div>
                <Label>Daily spend cap (₹)</Label>
                <Input
                  name="daily_spend_cap_inr"
                  type="number"
                  min={0}
                  step={1}
                  defaultValue={t.daily_spend_cap_inr ?? 600}
                />
              </div>
              <div>
                <Label>Avg order size (₹)</Label>
                <Input
                  name="avg_order_size_inr"
                  type="number"
                  min={0}
                  step={1000}
                  defaultValue={t.avg_order_size_inr ?? 200000}
                />
              </div>
              <div>
                <Label>Overage policy</Label>
                <select
                  name="overage_policy"
                  defaultValue={t.overage_policy ?? "continue_billed"}
                  className="block h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                >
                  <option value="continue_billed">
                    Continue past allowance (bill per unit)
                  </option>
                  <option value="hard_pause">
                    Hard pause when allowance hit
                  </option>
                </select>
              </div>
            </div>
          </div>

          <Button type="submit">Save</Button>
        </form>
      </main>
    </>
  );
}
