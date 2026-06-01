"use client";
import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { markDncAction } from "@/app/leads/actions";

export function DncDialog({
  leadId,
  phone,
}: {
  leadId: string;
  phone: string;
}) {
  const [pending, start] = useTransition();
  const router = useRouter();
  return (
    <Button
      variant="destructive"
      disabled={pending}
      onClick={() =>
        start(async () => {
          const r = await markDncAction(leadId, phone);
          if (r.error) toast.error(r.error);
          else {
            toast.success("Marked DNC");
            router.refresh();
          }
        })
      }
    >
      {pending ? "…" : "Mark DNC"}
    </Button>
  );
}
