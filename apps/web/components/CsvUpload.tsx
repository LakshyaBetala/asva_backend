"use client";
import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const COLUMNS = ["name", "phone", "company", "industry", "source", "notes"] as const;
const MAX_PREVIEW_ROWS = 5;

type ParsedCsv = {
  headers: string[];
  rows: string[][];
  totalRows: number;
};

function parseCsv(text: string): ParsedCsv {
  const lines = text.replace(/\r\n?/g, "\n").split("\n").filter((l) => l.trim().length > 0);
  if (lines.length === 0) return { headers: [], rows: [], totalRows: 0 };
  const split = (l: string): string[] =>
    l.match(/("([^"]|"")*"|[^,]*)(,|$)/g)?.map((c) =>
      c.replace(/,$/, "").trim().replace(/^"|"$/g, "").replace(/""/g, '"'),
    ).slice(0, -1) ?? l.split(",").map((s) => s.trim());
  const headers = split(lines[0]!).map((h) => h.toLowerCase().trim());
  const rows = lines.slice(1).map(split);
  return { headers, rows, totalRows: rows.length };
}

export function CsvUploadDialog() {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState<string>("");
  const [dragOver, setDragOver] = useState(false);
  const [isPending, start] = useTransition();
  const router = useRouter();

  const parsed = useMemo(() => (text ? parseCsv(text) : null), [text]);

  const missingColumns = useMemo(() => {
    if (!parsed) return [] as string[];
    const have = new Set(parsed.headers);
    return COLUMNS.filter((c) => c === "name" || c === "phone").filter((c) => !have.has(c));
  }, [parsed]);

  async function handleFile(f: File | null) {
    setFile(f);
    if (!f) {
      setText("");
      return;
    }
    try {
      const t = await f.text();
      setText(t);
    } catch {
      toast.error("could not read file");
    }
  }

  async function upload() {
    if (!text) return;
    if (missingColumns.length > 0) {
      toast.error(`Missing required columns: ${missingColumns.join(", ")}`);
      return;
    }
    start(async () => {
      const res = await fetch("/api/leads/import", { method: "POST", body: text });
      const body = await res.json();
      if (!res.ok) {
        toast.error(body.error ?? "upload failed");
        return;
      }
      toast.success(
        `Inserted ${body.inserted} · Invalid ${body.invalid.length} · Dupes ${body.duplicatesInFile.length}`,
      );
      setOpen(false);
      setFile(null);
      setText("");
      router.refresh();
    });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">Upload CSV</Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Upload leads CSV</DialogTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            Required columns: <code className="rounded bg-slate-100 px-1">name</code>,{" "}
            <code className="rounded bg-slate-100 px-1">phone</code>. Optional:{" "}
            <code className="rounded bg-slate-100 px-1">company</code>,{" "}
            <code className="rounded bg-slate-100 px-1">industry</code>,{" "}
            <code className="rounded bg-slate-100 px-1">source</code>,{" "}
            <code className="rounded bg-slate-100 px-1">notes</code>. Max 10,000 rows.
          </p>
        </DialogHeader>

        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const f = e.dataTransfer.files?.[0];
            if (f) handleFile(f);
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-8 transition",
            dragOver
              ? "border-primary bg-primary/5"
              : "border-slate-200 bg-slate-50/50 hover:bg-slate-50",
          )}
        >
          <span className="text-3xl" aria-hidden>📄</span>
          <span className="text-sm font-medium text-slate-700">
            {file ? file.name : "Drop a CSV here or click to choose"}
          </span>
          <span className="text-[11px] text-muted-foreground">
            UTF-8 encoded · header row required
          </span>
          <input
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
          />
        </label>

        {parsed && parsed.totalRows > 0 ? (
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">
                {parsed.totalRows.toLocaleString()} rows detected · showing first{" "}
                {Math.min(MAX_PREVIEW_ROWS, parsed.totalRows)}
              </span>
              {missingColumns.length > 0 ? (
                <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700">
                  Missing: {missingColumns.join(", ")}
                </span>
              ) : (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                  Columns OK
                </span>
              )}
            </div>
            <div className="overflow-hidden rounded-md border border-slate-200">
              <table className="w-full text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    {parsed.headers.map((h, i) => (
                      <th
                        key={i}
                        className={cn(
                          "px-2 py-1.5 text-left font-medium",
                          (h === "name" || h === "phone") && "text-emerald-700",
                        )}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {parsed.rows.slice(0, MAX_PREVIEW_ROWS).map((r, ri) => (
                    <tr key={ri} className="border-t border-slate-100">
                      {parsed.headers.map((_, ci) => (
                        <td key={ci} className="truncate px-2 py-1 text-slate-700">
                          {r[ci] ?? "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        <div className="mt-5 flex justify-end gap-2 border-t pt-4">
          <Button
            variant="outline"
            onClick={() => {
              setOpen(false);
              setFile(null);
              setText("");
            }}
            disabled={isPending}
          >
            Cancel
          </Button>
          <Button
            disabled={!text || isPending || missingColumns.length > 0}
            onClick={upload}
          >
            {isPending
              ? "Uploading…"
              : parsed
                ? `Import ${parsed.totalRows.toLocaleString()} rows`
                : "Upload"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
