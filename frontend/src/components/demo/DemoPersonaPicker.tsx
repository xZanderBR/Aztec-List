"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Loader2, ShieldCheck, ShoppingBag, Store } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { useAppConfig } from "@/hooks/useAppConfig";
import { DemoPersona } from "@/types/config";

const ROLE_ICON: Record<string, typeof Store> = {
  seller: Store,
  buyer: ShoppingBag,
  moderator: ShieldCheck,
};

interface DemoPersonaPickerProps {
  /** Where to go after logging in (defaults to the home page). */
  redirectTo?: string;
}

/** One-click login as a seeded demo account. Renders nothing outside demo mode. */
export function DemoPersonaPicker({ redirectTo = "/" }: DemoPersonaPickerProps) {
  const { isDemo, demo } = useAppConfig();
  const { demoLogin } = useAuth();
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);

  if (!isDemo || demo.personas.length === 0) return null;

  const choose = async (persona: DemoPersona) => {
    setPending(persona.key);
    try {
      await demoLogin(persona.key);
      toast.success(`Logged in as ${persona.name}`);
      router.push(redirectTo);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Demo login failed");
    } finally {
      setPending(null);
    }
  };

  return (
    <section aria-labelledby="demo-personas-heading" className="space-y-3">
      <div className="space-y-1 text-center">
        <h2 id="demo-personas-heading" className="text-lg font-semibold">
          Try the demo
        </h2>
        <p className="text-sm text-muted-foreground">Pick an account. No signup needed.</p>
      </div>
      <ul className="grid gap-2">
        {demo.personas.map((persona) => {
          const Icon = ROLE_ICON[persona.role] ?? Store;
          const isPending = pending === persona.key;
          return (
            <li key={persona.key}>
              <Button
                type="button"
                variant="outline"
                disabled={pending !== null}
                onClick={() => choose(persona)}
                aria-label={`Log in as ${persona.name} (${persona.role})`}
                className="h-auto w-full justify-start gap-3 py-3 text-left whitespace-normal"
              >
                {isPending ? (
                  <Loader2 className="h-5 w-5 shrink-0 animate-spin" aria-hidden />
                ) : (
                  <Icon className="h-5 w-5 shrink-0 text-purple-500" aria-hidden />
                )}
                <span className="flex flex-col gap-0.5">
                  <span className="font-medium">
                    {persona.name}{" "}
                    <span className="text-xs font-normal text-muted-foreground capitalize">
                      · {persona.role}
                    </span>
                  </span>
                  <span className="text-xs font-normal text-muted-foreground">{persona.blurb}</span>
                </span>
              </Button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
