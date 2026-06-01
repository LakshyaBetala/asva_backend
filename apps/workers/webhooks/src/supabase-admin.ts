import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export function adminClient(env: {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
}): SupabaseClient {
  return createClient(env.SUPABASE_URL, env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}
