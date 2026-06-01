"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

export function LeadsRealtimeRefresher() {
  const router = useRouter();
  useEffect(() => {
    const supabase = createSupabaseBrowserClient();
    const ch = supabase
      .channel("scores-refresh")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "lead_scores" },
        () => router.refresh(),
      )
      .subscribe();
    return () => {
      supabase.removeChannel(ch);
    };
  }, [router]);
  return null;
}
