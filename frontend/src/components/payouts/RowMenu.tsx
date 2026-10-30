// "⋯" menu on each creator row: the less common actions, kept out of the way.
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
  const run = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn()
      toast.success(done)
      onChanged()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Request failed")
    }
  }
  const mark = (action: BookingMarkAction, done: string) => run(() => payoutAdmin.markBooking(adminKey, row, action), done)
  const trust = (override: QueueRow["trust_override"], done: string) =>
    run(() => payoutAdmin.setTrust(adminKey, row.username, override), done)
  const copyLink = () =>
    run(async () => {
      const res = await payoutAdmin.links(adminKey, [row.username])
      await navigator.clipboard.writeText(dmFor(res.links[0].link))
    }, `DM with @${row.handle}'s link copied`)

  const marked = !row.payment && (row.reason === "trusted_confirmed" || row.reason === "manual")

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" aria-label={`More for @${row.handle}`} className="px-1.5 text-rt-fg-tertiary hover:text-rt-fg">
          ⋯
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={copyLink}>Copy DM with their dashboard link</DropdownMenuItem>
        {row.reason === "posts_incomplete" && !row.payment && (
          <DropdownMenuItem onSelect={() => mark("ready", `@${row.handle} marked owed (paying early)`)}>
            Pay early (before all posts are in)
          </DropdownMenuItem>
        )}
        {marked && (
          <DropdownMenuItem onSelect={() => mark("clear", "Undone")}>
            {row.reason === "trusted_confirmed" ? "Undo confirm" : "Undo pay early"}
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
  )
}
