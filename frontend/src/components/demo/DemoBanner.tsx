"use client";

import { useEffect, useState } from "react";
import { FlaskConical } from "lucide-react";
import { useAppConfig } from "@/hooks/useAppConfig";

export const REPO_URL = "https://github.com/xZanderBR/aztec-list";

/** "3h 12m" / "12m" until the given ISO time (never negative). */
export function formatTimeUntil(iso: string, now: number): string {
  const minutes = Math.max(0, Math.round((new Date(iso).getTime() - now) / 60000));
  const hours = Math.floor(minutes / 60);
  return hours > 0 ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
}

/** Slim site-wide notice shown only on the sandbox demo deployment. */
export function DemoBanner() {
  const { isDemo, demo } = useAppConfig();
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (!isDemo) return;
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0); // client-only: avoids a server/client time mismatch
    const id = setInterval(tick, 60_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [isDemo]);

  if (!isDemo) return null;

  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 border-b border-purple-500/30 bg-purple-600/10 px-4 py-1.5 text-center text-sm"
    >
      <FlaskConical className="h-4 w-4 text-purple-500" aria-hidden />
      <span>
        <span className="font-medium">Sandbox demo.</span> Try anything; all data resets
        {demo.next_reset_at && now !== null
          ? ` in ${formatTimeUntil(demo.next_reset_at, now)}`
          : " every few hours"}
        .
      </span>
      <a
        href={REPO_URL}
        target="_blank"
        rel="noreferrer"
        className="font-medium text-purple-600 underline-offset-4 hover:underline dark:text-purple-400"
      >
        View source
      </a>
    </div>
  );
}
