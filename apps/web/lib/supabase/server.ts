import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";

export function createSupabaseServerClient() {
  const cookieStore = cookies();
  const bypass = process.env.DEV_BYPASS_AUTH === "1";
  const key = bypass
    ? process.env.SUPABASE_SERVICE_ROLE_KEY!
    : process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;
  return createServerClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, key, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (toSet: { name: string; value: string; options?: CookieOptions }[]) => {
        try {
          toSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options),
          );
        } catch {
          // Server Component context — ignore
        }
      },
    },
  });
}
