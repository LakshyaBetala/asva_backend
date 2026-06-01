import { NextResponse } from "next/server";
import { parseLeadsCsv } from "@ai-voice/shared";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const text = await req.text();
  if (!text) return NextResponse.json({ error: "empty body" }, { status: 400 });

  let parsed;
  try {
    parsed = parseLeadsCsv(text);
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 400 });
  }

  const supabase = createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const { data: profile } = await supabase
    .from("users")
    .select("tenant_id")
    .eq("id", user.id)
    .single();
  if (!profile?.tenant_id)
    return NextResponse.json({ error: "no tenant" }, { status: 403 });

  const rows = parsed.valid.map((v) => ({
    ...v,
    tenant_id: profile.tenant_id,
    status: "new" as const,
  }));
  if (rows.length > 0) {
    const { error } = await supabase.from("leads").insert(rows);
    if (error)
      return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    inserted: rows.length,
    invalid: parsed.invalid,
    duplicatesInFile: parsed.duplicatesInFile,
  });
}
