"use server";
import { revalidatePath } from "next/cache";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export async function startBulkAction(): Promise<{
  ok?: boolean;
  error?: string;
  dispatched?: number;
}> {
  const url = process.env.CAMPAIGNS_WORKER_URL;
  const token = process.env.INTERNAL_API_TOKEN;
  if (!url || !token) return { error: "campaigns worker not configured" };

  const supabase = createSupabaseServerClient();
  const { data: leads } = await supabase
    .from("leads")
    .select("id")
    .eq("status", "new")
    .limit(50);
  if (!leads?.length) return { ok: true, dispatched: 0 };

  let dispatched = 0;
  for (const l of leads) {
    const res = await fetch(`${url}/dispatch`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ lead_id: l.id }),
    });
    if (res.ok) dispatched++;
    await new Promise((r) => setTimeout(r, 1000));
  }
  revalidatePath("/leads");
  revalidatePath("/campaigns");
  return { ok: true, dispatched };
}
