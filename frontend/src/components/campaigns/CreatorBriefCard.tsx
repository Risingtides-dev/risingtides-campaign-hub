import { useState } from "react"
import { toast } from "sonner"
import { useSetCreatorBrief } from "@/lib/queries"

const MAX = 5000

// What creators see as "Brief" on their dashboard. Kept in the Hub because
// the CRM notes field mixes creative direction with budget/billing info.
export function CreatorBriefCard({ slug, brief }: { slug: string; brief: string }) {
  const [value, setValue] = useState(brief)
  const save = useSetCreatorBrief(slug)
  const dirty = value.trim() !== brief.trim()

  return (
    <section className="rounded-[10px] bg-rt-bg-card border border-white/8 p-4 space-y-2">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-rt-fg">Creator brief</h2>
        <span className="text-xs text-rt-fg-tertiary">Shown to booked creators · blank = "Open creative"</span>
      </div>
      <textarea
        value={value}
        maxLength={MAX}
        rows={3}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Open creative"
        className="w-full rounded-md border border-white/10 bg-rt-bg-black px-3 py-2 text-sm text-rt-fg"
      />
      <p className="text-xs text-rt-amber">Creators see this exactly as written — no budgets, rates or client details.</p>
      <button
        type="button"
        disabled={!dirty || save.isPending}
        onClick={() =>
          save.mutate(value, {
            onSuccess: () => toast.success("Brief saved"),
            onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't save brief"),
          })
        }
        className="rounded-md bg-rt-magenta px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40"
      >
        {save.isPending ? "Saving…" : "Save brief"}
      </button>
    </section>
  )
}
