import { redirect } from "next/navigation";
import { createSupabaseServerClient } from "./supabase/server";

const DEV_BYPASS = process.env.DEV_BYPASS_AUTH === "1";
const BYPASS_USER_ID = "2fdc881f-3883-4838-90ea-6bcb09a8e5d2";
const BYPASS_EMAIL = "almmatix@gmail.com";
const BYPASS_TENANT_ID = "f39df33f-0c93-4115-a56f-0e19ab926c3c";

export async function getCurrentUser() {
  if (DEV_BYPASS) {
    return { id: BYPASS_USER_ID, email: BYPASS_EMAIL } as unknown as Awaited<
      ReturnType<Awaited<ReturnType<typeof createSupabaseServerClient>>["auth"]["getUser"]>
    >["data"]["user"];
  }
  const supabase = createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  return user;
}

export async function requireTenant() {
  if (DEV_BYPASS) {
    return {
      user: { id: BYPASS_USER_ID, email: BYPASS_EMAIL } as unknown as NonNullable<
        Awaited<ReturnType<typeof getCurrentUser>>
      >,
      tenantId: BYPASS_TENANT_ID,
      role: "admin" as const,
    };
  }
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const supabase = createSupabaseServerClient();
  const { data } = await supabase
    .from("users")
    .select("tenant_id, role")
    .eq("id", user.id)
    .single();
  if (!data?.tenant_id) redirect("/login");
  return { user, tenantId: data.tenant_id, role: data.role as "admin" | "rep" };
}
