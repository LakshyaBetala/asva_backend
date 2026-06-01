"use client";
import { useEffect, useState } from "react";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

type Line = {
  id: string;
  speaker: "agent" | "lead";
  text: string;
  lang: string;
  ts_ms: number;
  idx: number;
};

export function TranscriptView({ leadId }: { leadId: string }) {
  const [callId, setCallId] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);

  useEffect(() => {
    const supabase = createSupabaseBrowserClient();
    let mounted = true;
    (async () => {
      const { data } = await supabase
        .from("calls")
        .select("id")
        .eq("lead_id", leadId)
        .eq("kind", "ai_outbound")
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle();
      if (mounted && data?.id) setCallId(data.id);
    })();
    return () => {
      mounted = false;
    };
  }, [leadId]);

  useEffect(() => {
    if (!callId) return;
    const supabase = createSupabaseBrowserClient();
    let active = true;
    (async () => {
      const { data } = await supabase
        .from("transcripts")
        .select("id,speaker,text,lang,ts_ms,idx")
        .eq("call_id", callId)
        .order("idx", { ascending: true });
      if (active) setLines((data ?? []) as Line[]);
    })();
    const ch = supabase
      .channel(`tx-${callId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "transcripts",
          filter: `call_id=eq.${callId}`,
        },
        (p: { new: Line }) =>
          setLines((prev) =>
            [...prev, p.new].sort((a, b) => a.idx - b.idx),
          ),
      )
      .subscribe();
    return () => {
      active = false;
      supabase.removeChannel(ch);
    };
  }, [callId]);

  if (!callId) {
    return (
      <p className="text-sm text-muted-foreground">
        No call yet. Click <strong>Call with AI</strong> to start one.
      </p>
    );
  }
  if (lines.length === 0) {
    return <p className="text-sm text-muted-foreground">Connecting…</p>;
  }
  return (
    <div className="max-h-96 space-y-3 overflow-y-auto">
      {lines.map((l) => (
        <div
          key={l.id}
          className={l.speaker === "agent" ? "" : "pl-8"}
        >
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {l.speaker === "agent" ? "Priya" : "Lead"} · {l.lang}
          </span>
          <p className="text-sm">{l.text}</p>
        </div>
      ))}
    </div>
  );
}
