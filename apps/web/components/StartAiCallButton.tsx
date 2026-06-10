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
import { toast } from "sonner";
import { startAiCallAction } from "@/app/leads/actions";
import { cn } from "@/lib/utils";

type Lang = "ta-IN" | "hi-IN" | "en-IN";
type Gender = "female" | "male";

const LANGS: { code: Lang; label: string; sub: string; flag: string }[] = [
  { code: "ta-IN", label: "Tamil", sub: "தமிழ்", flag: "🇮🇳" },
  { code: "hi-IN", label: "Hindi", sub: "हिन्दी", flag: "🇮🇳" },
  { code: "en-IN", label: "English", sub: "Indian", flag: "🇮🇳" },
];

const VOICES: { code: Gender; label: string; persona: string; emoji: string }[] = [
  { code: "female", label: "Priya", persona: "Female, warm Chennai-based BD", emoji: "👩" },
  { code: "male", label: "Pranav", persona: "Male, steady Chennai-based BD", emoji: "👨" },
];

export function StartAiCallButton({
  leadId,
  defaultLang = "ta-IN",
  defaultGender = "female",
}: {
  leadId: string;
  defaultLang?: Lang;
  defaultGender?: Gender;
}) {
  const [open, setOpen] = useState(false);
  const [lang, setLang] = useState<Lang>(defaultLang);
  const [gender, setGender] = useState<Gender>(defaultGender);
  const [pending, start] = useTransition();
  const router = useRouter();

  function fire() {
    start(async () => {
      const r = await startAiCallAction(leadId, { lang, gender });
      if (r.error) toast.error(r.error);
      else {
        toast.success(
          `Calling now — ${LANGS.find((l) => l.code === lang)!.label} · ${
            VOICES.find((v) => v.code === gender)!.label
          }`,
        );
        setOpen(false);
        router.refresh();
      }
    });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="gap-2">
          <span aria-hidden>📞</span>
          <span>Call with AI</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Start AI call</DialogTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            Pick the language and voice. Priya will dial in ~2 seconds.
          </p>
        </DialogHeader>

        <div className="space-y-5">
          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Language
            </div>
            <div className="grid grid-cols-3 gap-2">
              {LANGS.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  onClick={() => setLang(l.code)}
                  className={cn(
                    "flex flex-col items-center gap-1 rounded-lg border p-3 text-left transition",
                    lang === l.code
                      ? "border-primary bg-primary/5 ring-2 ring-primary/20"
                      : "border-border hover:border-input hover:bg-muted/50",
                  )}
                >
                  <span className="text-base leading-none">{l.flag}</span>
                  <span className="text-sm font-medium">{l.label}</span>
                  <span className="text-[10px] text-muted-foreground">{l.sub}</span>
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Voice
            </div>
            <div className="grid grid-cols-2 gap-2">
              {VOICES.map((v) => (
                <button
                  key={v.code}
                  type="button"
                  onClick={() => setGender(v.code)}
                  className={cn(
                    "flex items-start gap-3 rounded-lg border p-3 text-left transition",
                    gender === v.code
                      ? "border-primary bg-primary/5 ring-2 ring-primary/20"
                      : "border-border hover:border-input hover:bg-muted/50",
                  )}
                >
                  <span className="text-xl leading-none">{v.emoji}</span>
                  <span>
                    <span className="block text-sm font-medium">{v.label}</span>
                    <span className="block text-[11px] text-muted-foreground">
                      {v.persona}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2 border-t pt-4">
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={pending}
            >
              Cancel
            </Button>
            <Button onClick={fire} disabled={pending} className="gap-2">
              {pending ? (
                <>
                  <span className="inline-block h-3 w-3 animate-pulse rounded-full bg-current" />
                  Dialing…
                </>
              ) : (
                <>
                  <span aria-hidden>📞</span>
                  Dial now
                </>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
