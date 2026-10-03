import { useState } from "react"
import { toast } from "sonner"
import { Loader2, X } from "lucide-react"
import { useAddLibraryCreator } from "@/lib/queries"
import type { LibraryNiche } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { NichePicker } from "./NichePicker"
import { nicheStyle } from "./nicheColors"

/**
 * Add a creator scouted off-platform, before any booking exists.
 *
 * They land with no campaign history, which the library renders as dashes
 * rather than zeros — an unbooked creator has unknown performance, not bad
 * performance. The rate captured here is their asking price and auto-fills
 * the first time they're added to a campaign.
 */
export function AddCreatorDialog({
  niches,
  onClose,
}: {
  niches: LibraryNiche[]
  onClose: () => void
}) {
  const [username, setUsername] = useState("")
  const [rate, setRate] = useState("")
  const [paypal, setPaypal] = useState("")
  const [tags, setTags] = useState<string[]>([])
  const [pickerAnchor, setPickerAnchor] = useState<HTMLElement | null>(null)

  const add = useAddLibraryCreator()

  async function submit() {
    const handle = username.trim().replace(/^@/, "")
    if (!handle) {
      toast.error("Enter a username")
      return
    }
    const parsed = rate.trim() ? parseFloat(rate) : null
    if (rate.trim() && (Number.isNaN(parsed as number) || (parsed as number) <= 0)) {
      toast.error("Rate must be a number greater than zero")
      return
    }
    try {
      await add.mutateAsync({
        username: handle,
        rate: parsed,
        niches: tags,
        paypal_email: paypal.trim() || undefined,
      })
      toast.success(`@${handle} added to the library`)
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't add that creator")
    }
  }

  return (
    <div className="fixed inset-0 z-[110] grid place-items-center bg-black/70 p-6">
      <div className="flex w-full max-w-[560px] flex-col overflow-hidden rounded-2xl border border-white/15 bg-rt-bg-raised shadow-2xl">
        <header className="flex items-center gap-3 border-b border-white/10 px-5 py-4">
          <h2 className="text-[17px] font-semibold text-rt-fg">Add a creator</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto rounded-lg p-1 text-rt-fg-tertiary hover:bg-rt-bg-card hover:text-rt-fg"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="space-y-4 p-5">
          <label className="block">
            <span className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
              TikTok username
            </span>
            <Input
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="creator.handle"
            />
            <span className="mt-1.5 block text-[11.5px] text-rt-fg-tertiary">
              No @ needed. Campaign stats stay blank until you book them.
            </span>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
              Rate per post
            </span>
            <Input
              type="number"
              step="0.01"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              placeholder="35"
            />
            <span className="mt-1.5 block text-[11.5px] text-rt-fg-tertiary">
              What they're asking. Auto-fills when you add them to a campaign.
            </span>
          </label>

          <div>
            <span className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
              Niches
            </span>
            <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-rt-bg-card p-2.5">
              {tags.map((name) => (
                <span
                  key={name}
                  style={nicheStyle(name)}
                  className="inline-flex items-center gap-1 rounded-full py-0.5 pl-2.5 pr-1.5 text-[11px] font-semibold"
                >
                  {name}
                  <button
                    type="button"
                    aria-label={`Remove ${name}`}
                    onClick={() => setTags((t) => t.filter((n) => n !== name))}
                    className="opacity-60 hover:opacity-100"
                  >
                    <X className="size-2.5" />
                  </button>
                </span>
              ))}
              <button
                type="button"
                onClick={(e) => setPickerAnchor(e.currentTarget)}
                className="rounded-full border border-dashed border-white/20 px-3 py-0.5 text-[11.5px] font-semibold text-rt-fg-tertiary hover:border-rt-magenta hover:text-rt-fg"
              >
                + add niche
              </button>
            </div>
          </div>

          <label className="block">
            <span className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
              PayPal (optional)
            </span>
            <Input
              type="email"
              value={paypal}
              onChange={(e) => setPaypal(e.target.value)}
              placeholder="creator@email.com"
            />
          </label>
        </div>

        <footer className="flex items-center gap-3 border-t border-white/10 px-5 py-3.5">
          <span className="flex-1 text-[12px] text-rt-fg-tertiary">
            They'll show dashes for views and CPM until their first booking.
          </span>
          <Button onClick={submit} disabled={add.isPending}>
            {add.isPending && <Loader2 className="size-3.5 animate-spin" />}
            Add to library
          </Button>
        </footer>
      </div>

      {pickerAnchor && (
        <NichePicker
          anchor={pickerAnchor}
          niches={niches}
          selected={tags}
          onToggle={(name) =>
            setTags((t) => (t.includes(name) ? t.filter((n) => n !== name) : [...t, name]))
          }
          onCreate={(name) => setTags((t) => (t.includes(name) ? t : [...t, name]))}
          onClose={() => setPickerAnchor(null)}
        />
      )}
    </div>
  )
}
