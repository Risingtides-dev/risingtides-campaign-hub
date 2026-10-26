// Labels for the "dashboard sent to point of contact" checkbox.

export function formatSentDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}

export function dashboardSentLabel(sentAt: string): string {
  if (!sentAt) return "Mark dashboard sent to point of contact"
  const when = formatSentDate(sentAt)
  return `Dashboard sent to point of contact${when ? ` on ${when}` : ""} — click to undo`
}
