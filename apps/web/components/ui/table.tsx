import * as React from "react";
import { cn } from "@/lib/utils";

export const Table = ({ className, ...p }: React.HTMLAttributes<HTMLTableElement>) => (
  <div className="w-full overflow-auto rounded-md border">
    <table className={cn("w-full caption-bottom text-sm", className)} {...p} />
  </div>
);
export const TableHeader = (p: React.HTMLAttributes<HTMLTableSectionElement>) => (
  <thead className="bg-muted" {...p} />
);
export const TableBody = (p: React.HTMLAttributes<HTMLTableSectionElement>) => (
  <tbody {...p} />
);
export const TableRow = ({ className, ...p }: React.HTMLAttributes<HTMLTableRowElement>) => (
  <tr className={cn("border-b transition-colors hover:bg-muted/50", className)} {...p} />
);
export const TableHead = ({ className, ...p }: React.ThHTMLAttributes<HTMLTableCellElement>) => (
  <th className={cn("h-10 px-3 text-left align-middle font-medium text-muted-foreground", className)} {...p} />
);
export const TableCell = ({ className, ...p }: React.TdHTMLAttributes<HTMLTableCellElement>) => (
  <td className={cn("p-3 align-middle", className)} {...p} />
);
