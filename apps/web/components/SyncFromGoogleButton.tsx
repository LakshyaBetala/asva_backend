"use client";
import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export function SyncFromGoogleButton() {
  const [isPending, start] = useTransition();
  const router = useRouter();

  async function sync() {
    start(async () => {
      const res = await fetch("/api/leads/sync/places", { method: "POST" });
      const body = await res.json();
      if (!res.ok) {
        toast.error(body.error ?? "Sync failed", {
          description: body.hint,
        });
        return;
      }
      const errorTail =
        body.errors?.length > 0 ? ` (${body.errors.length} query errors)` : "";
      toast.success(
        `+${body.inserted} new · ${body.duplicates} dupes · ${body.queries} queries${errorTail}`,
      );
      router.refresh();
    });
  }

  return (
    <Button variant="outline" onClick={sync} disabled={isPending}>
      {isPending ? "Syncing…" : "Sync from Google"}
    </Button>
  );
}
