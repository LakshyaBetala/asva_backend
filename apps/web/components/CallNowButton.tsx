"use client";
import { useEffect, useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { bridgeCallAction } from "@/app/leads/actions";

export function CallNowButton({
  leadId,
  phone,
}: {
  leadId: string;
  phone: string;
}) {
  const [pending, start] = useTransition();
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    if (typeof navigator !== "undefined") {
      setIsMobile(/Android|iPhone|iPad|iPod/i.test(navigator.userAgent));
    }
  }, []);

  if (isMobile) {
    return (
      <a href={`tel:${phone}`} className="inline-flex">
        <Button variant="default">📞 Call now</Button>
      </a>
    );
  }
  return (
    <Button
      disabled={pending}
      onClick={() =>
        start(async () => {
          const r = await bridgeCallAction(leadId);
          if (r.error) toast.error(r.error);
          else
            toast.success(
              "Your phone will ring — pick up to be connected to the lead",
            );
        })
      }
    >
      {pending ? "Bridging…" : "📞 Call now"}
    </Button>
  );
}
