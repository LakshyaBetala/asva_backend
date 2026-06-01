"use client";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { addLeadAction } from "@/app/leads/actions";

export function ManualLeadDialog() {
  const [open, setOpen] = useState(false);
  const [isPending, start] = useTransition();
  const router = useRouter();

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>Add lead</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a lead</DialogTitle>
        </DialogHeader>
        <form
          action={(fd) =>
            start(async () => {
              const res = await addLeadAction(fd);
              if (res.error) toast.error(res.error);
              else {
                toast.success("Lead added");
                setOpen(false);
                router.refresh();
              }
            })
          }
          className="space-y-3"
        >
          <div>
            <Label>Name</Label>
            <Input name="name" required placeholder="Ravi Kumar" />
          </div>
          <div>
            <Label>Phone</Label>
            <Input name="phone" required placeholder="9876543210" />
          </div>
          <div>
            <Label>Company</Label>
            <Input name="company" placeholder="Acme Pharma" />
          </div>
          <div>
            <Label>Industry</Label>
            <Input name="industry" placeholder="Pharmaceuticals" />
          </div>
          <div className="flex justify-end">
            <Button type="submit" disabled={isPending}>
              {isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
