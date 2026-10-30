import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { toast } from "sonner"
import { dmFor, parseHandles, payoutAdmin } from "@/lib/payouts"
import type { PayoutLink } from "@/lib/payouts"

export function PayoutLinkGenerator({ adminKey, onIssued }: { adminKey: string; onIssued: () => void }) {
  const [text, setText] = useState("")
  const [links, setLinks] = useState<PayoutLink[]>([])

  const generate = useMutation({
    mutationFn: (handles: string[]) => payoutAdmin.links(adminKey, handles),
    onSuccess: (res) => {
      setLinks(res.links)
      if (res.skipped.length) toast.error(`Skipped: ${res.skipped.join(", ")}`)
      onIssued()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't generate links"),
  })

  const copy = async (value: string, what: string) => {
    try {
      await navigator.clipboard.writeText(value)
      toast.success(`${what} copied`)
    } catch {
      toast.error("Clipboard blocked — select and copy manually")
    }
  }

  const handles = parseHandles(text)

  return (
    <section className="rounded-xl bg-rt-bg-card border border-white/8 p-4 space-y-3">
      <h2 className="text-sm font-semibold text-rt-fg">Payment-info links</h2>
      <p className="text-xs text-rt-fg-tertiary">
        Paste handles (one per line or comma-separated). Existing links are reused; each link is private to that
        creator — only send it in their DM.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="@creator1, @creator2"
        className="w-full rounded-md border border-white/10 bg-rt-bg-black px-3 py-2 text-sm text-rt-fg"
      />
      <button
        type="button"
        disabled={!handles.length || generate.isPending}
        onClick={() => generate.mutate(handles)}
        className="rounded-md bg-rt-magenta px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
      >
        {generate.isPending ? "Generating…" : `Get ${handles.length || ""} link${handles.length === 1 ? "" : "s"}`}
      </button>

      {links.length > 0 && (
        <ul className="divide-y divide-white/5">
          {links.map((l) => (
            <li key={l.username} className="py-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm text-rt-fg">
                @{l.handle}
                {l.has_destination && <span className="ml-2 text-xs text-rt-fg-tertiary">(has details on file)</span>}
              </span>
              <span className="flex gap-3">
                <button type="button" className="text-xs text-rt-magenta hover:underline"
                  onClick={() => copy(dmFor(l.link), "DM")}>
                  Copy DM
                </button>
                <button type="button" className="text-xs text-rt-fg-secondary hover:underline"
                  onClick={() => copy(l.link, "Link")}>
                  Copy link
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
