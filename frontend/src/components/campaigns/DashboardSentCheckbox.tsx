import { Send } from "lucide-react"
import { dashboardSentLabel } from "@/components/campaigns/dashboardSent"

// "Client dashboard handed to the point of contact" — shared by the
// campaigns list row and the campaign page header so both look and read
// the same.

export function DashboardSentBox({ sent }: { sent: boolean }) {
  return (
    <span
      aria-hidden="true"
      // flex in BOTH states: a bare <span> is inline, so without it the
      // unchecked box ignores size-5 and collapses to a thin line.
      className={
        sent
          ? "size-5 shrink-0 rounded border border-sky-400/40 bg-sky-400/10 flex items-center justify-center"
          : "size-5 shrink-0 rounded border border-white/10 bg-rt-bg-card flex items-center justify-center hover:border-white/20 transition-colors"
      }
    >
      {sent && <Send className="size-3 text-sky-400" />}
    </span>
  )
}

/** Bare checkbox — campaigns list rows. */
export function DashboardSentCheckbox({
  sentAt,
  onClick,
}: {
  sentAt: string
  onClick: (e: React.MouseEvent) => void
}) {
  const label = dashboardSentLabel(sentAt)
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={Boolean(sentAt)}
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex rounded hover:opacity-80 transition-opacity"
    >
      <DashboardSentBox sent={Boolean(sentAt)} />
    </button>
  )
}
