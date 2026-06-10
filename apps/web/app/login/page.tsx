import { redirect } from "next/navigation";
import { signInAction } from "./actions";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  if (process.env.DEV_BYPASS_AUTH === "1") redirect("/leads");
  return (
    <main className="mx-auto mt-24 max-w-sm space-y-6 p-6">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Sign in</h1>
        <p className="text-sm text-muted-foreground">Almmatix Voice — Broker CRM</p>
      </div>
      <form
        action={async (fd: FormData) => {
          "use server";
          await signInAction(fd);
        }}
        className="space-y-4"
      >
        <div>
          <Label htmlFor="email">Email</Label>
          <Input id="email" name="email" type="email" required placeholder="you@brokerage.in" />
        </div>
        <div>
          <Label htmlFor="password">Password</Label>
          <Input id="password" name="password" type="password" required />
        </div>
        <Button type="submit" className="w-full">Sign in</Button>
      </form>
    </main>
  );
}
