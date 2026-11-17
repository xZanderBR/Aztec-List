import { Lock } from "lucide-react";

/** Explains why a section is read-only on the sandbox demo. */
export function DemoLockedNotice({ what = "Account changes" }: { what?: string }) {
  return (
    <p
      role="note"
      className="mb-3 flex items-center gap-2 rounded-md border border-purple-500/30 bg-purple-600/10 px-3 py-2 text-sm"
    >
      <Lock className="h-4 w-4 shrink-0 text-purple-500" aria-hidden />
      {what}: disabled in the demo, since these accounts are shared with other visitors.
    </p>
  );
}
