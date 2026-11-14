// "⋯" menu on each creator row: the less common actions, kept out of the way.
import { useState } from "react"
import { usePayoutSessionIsActive } from "@/lib/payoutSession"
import { toast } from "sonner"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { dmFor, payoutAdmin } from "@/lib/payouts"
import type { BookingMarkAction, QueueRow } from "@/lib/payouts"

interface Props {
  row: QueueRow
  adminKey: string
  onChanged: () => void
}

export function RowMenu({ row, adminKey, onChanged }: Props) {
  const isActive = usePayoutSessionIsActive()
  const [manualCopy, setManualCopy] = useState("")
  const run = async (fn: () => Promise<unknown>, done: string) => {
    if (!isActive()) return
    try {
      await fn()
      if (!isActive()) return
      toast.success(done)
      onChanged()
    } catch (e) {
      if (isActive()) toast.error(e instanceof Error ? e.message : "Request failed")
    }
  }
  const mark = (action: BookingMarkAction, done: string) => run(() => payoutAdmin.markBooking(adminKey, row, action), done)
  const trust = (override: QueueRow["trust_override"], done: string) =>
    run(() => payoutAdmin.setTrust(adminKey, row.username, override), done)
  const copyLink = async () => {
    if (!isActive()) return
    try {
      const response = await payoutAdmin.links(adminKey, [row.username])
      if (!isActive()) return
      const link = response.links.find((item) => item.username.toLowerCase() === row.username.toLowerCase())?.link
      if (!link) throw new Error("No dashboard link returned.")
      const message = dmFor(link)
      setManualCopy("")
      try {
        await navigator.clipboard.writeText(message)
        if (isActive()) toast.success(`DM with @${row.handle}'s link copied`)
      } catch {
        if (isActive()) {
          setManualCopy(message)
          toast.error("Clipboard blocked. Copy the message below.")
        }
      }
      if (isActive()) onChanged()
    } catch (error) {
      if (isActive()) toast.error(error instanceof Error ? error.message : "Couldn't get dashboard link")
    }
  }

  const marked = !row.booking_issue && !row.payment && (row.reason === "trusted_confirmed" || row.reason === "manual")

  return (
    <div>
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" aria-label={`More for @${row.handle}`} className="px-1.5 text-rt-fg-tertiary hover:text-rt-fg">
          ⋯
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={copyLink}>Copy DM with their dashboard link</DropdownMenuItem>
        {!row.booking_issue && row.reason === "posts_incomplete" && !row.payment && (
          <DropdownMenuItem onSelect={() => mark("ready", `@${row.handle} marked ready early`)}>
            Mark ready early
          </DropdownMenuItem>
        )}
        {marked && (
          <DropdownMenuItem onSelect={() => mark("clear", "Undone")}>
            {row.reason === "trusted_confirmed" ? "Undo confirm" : "Undo early readiness"}
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        {row.trust_override !== "trusted" && (
          <DropdownMenuItem onSelect={() => trust("trusted", `@${row.handle} is now always trusted`)}>
            Always treat as trusted
          </DropdownMenuItem>
        )}
        {row.trust_override !== "standard" && (
          <DropdownMenuItem onSelect={() => trust("standard", `@${row.handle} is now always new`)}>
            Always treat as new
          </DropdownMenuItem>
        )}
        {row.trust_override !== "" && (
          <DropdownMenuItem onSelect={() => trust("", "Back to automatic")}>
            Automatic ({row.delivered_campaigns} campaigns done)
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
    {manualCopy && <textarea readOnly aria-label={`Dashboard message for @${row.handle}`} value={manualCopy} className="mt-2 w-64 rounded border border-white/10 bg-rt-bg-black px-2 py-1 text-xs text-rt-fg" />}
    </div>
  )
}
