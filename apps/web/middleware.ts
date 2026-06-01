import { updateSession } from "@/lib/supabase/middleware";
export const middleware = updateSession;
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/leads/import).*)"],
};
