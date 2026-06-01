"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

type Ctx = { open: boolean; setOpen: (v: boolean) => void };
const DialogCtx = React.createContext<Ctx | null>(null);

export function Dialog({
  open: openProp,
  onOpenChange,
  children,
}: {
  open?: boolean;
  onOpenChange?: (v: boolean) => void;
  children: React.ReactNode;
}) {
  const [internal, setInternal] = React.useState(false);
  const open = openProp ?? internal;
  const setOpen = (v: boolean) => {
    setInternal(v);
    onOpenChange?.(v);
  };
  return (
    <DialogCtx.Provider value={{ open, setOpen }}>{children}</DialogCtx.Provider>
  );
}

export function DialogTrigger({
  asChild,
  children,
}: {
  asChild?: boolean;
  children: React.ReactElement;
}) {
  const ctx = React.useContext(DialogCtx)!;
  const handler = () => ctx.setOpen(true);
  if (asChild) {
    return React.cloneElement(children, { onClick: handler });
  }
  return <button onClick={handler}>{children}</button>;
}

export function DialogContent({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ctx = React.useContext(DialogCtx)!;
  if (!ctx.open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={() => ctx.setOpen(false)}
    >
      <div
        className={cn(
          "w-full max-w-lg rounded-lg border bg-background p-6 shadow-lg",
          className,
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

export function DialogHeader({ children }: { children: React.ReactNode }) {
  return <div className="mb-4">{children}</div>;
}
export function DialogTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-lg font-semibold">{children}</h2>;
}
