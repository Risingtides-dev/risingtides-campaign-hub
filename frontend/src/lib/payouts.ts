// Creator payout API (Round 1). Kept separate from api.ts because the public
// creator page must not pull in the rest of the Hub, and the admin calls
// carry their own key header.

const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:5055" : "")

export type PayoutMethod = "paypal" | "cashapp" | "venmo" | "other"

export const PAYOUT_METHODS: { value: PayoutMethod; label: string; placeholder: string }[] = [
  { value: "paypal", label: "PayPal", placeholder: "you@email.com" },
  { value: "cashapp", label: "Cash App", placeholder: "$yourcashtag" },
  { value: "venmo", label: "Venmo", placeholder: "@your-venmo" },
  { value: "other", label: "Other", placeholder: "Tell us how to pay you" },
]

export const METHOD_LABEL: Record<string, string> = Object.fromEntries(
  PAYOUT_METHODS.map((m) => [m.value, m.label]),
)

export function money(n: number): string {
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 })}`
}

export interface PayoutPublicView {
  handle: string
  method: PayoutMethod | ""
  destination_masked: string
  confirmed: boolean
}

export interface CreatorBookingCard {
  campaign: string
  artist: string
  song: string
  start_date: string
  platforms: string[]
  sounds: { platform: string; url: string }[]
  brief: string
  open_creative: boolean
  captions: string[]
  posts_owed: number
  posts_done: number
  rate: number
  status: "in_progress" | "complete" | "paid"
  active: boolean
}

export interface CreatorPayment {
  campaign: string
  amount: number
  date: string
  platform: string
}

export interface CreatorDashboardData {
  creator: PayoutPublicView
  current: CreatorBookingCard[]
  payments: CreatorPayment[]
  totals: { paid: number; campaigns: number }
}

export interface PayoutSubmitResult extends PayoutPublicView {
  ok: true
  result: "created" | "changed" | "confirmed"
}

export interface PayoutAdminRow {
  username: string
  handle: string
  method: PayoutMethod | ""
  destination: string
  confirmed: boolean
  flagged: boolean
  has_link: boolean
  updated_at: string
}

export interface PayoutAdminOverview {
  creators: PayoutAdminRow[]
  summary: {
    total: number
    confirmed: number
    unconfirmed_on_file: number
    missing: number
    flagged: number
    links_issued: number
  }
}

export interface PayoutEvent {
  id: number
  event: string
  source: string
  old_method: string
  old_destination: string
  new_method: string
  new_destination: string
  created_at: string
}

export interface PayoutLink {
  username: string
  handle: string
  link: string
  newly_issued: boolean
  has_destination: boolean
}

export interface QueueRow {
  slug: string
  campaign: string
  username: string
  handle: string
  platform: string
  amount: number
  posts_owed: number
  posts_done: number
  reason: "posts_complete" | "trusted_confirmed" | "manual" | "trusted_unconfirmed" | "posts_incomplete"
  trusted: boolean
  trust_override: "" | "trusted" | "standard"
  delivered_campaigns: number
  method: PayoutMethod | ""
  destination: string
  destination_issue: "" | "missing" | "unconfirmed" | "changed"
}

export interface PaymentQueue {
  ready: QueueRow[]
  awaiting_confirmation: QueueRow[]
  not_ready: QueueRow[]
  totals: { ready_count: number; ready_amount: number; payable_now: number; by_method: Record<string, number> }
  trusted_min_campaigns: number
}

export type BookingMarkAction = "confirm" | "ready" | "clear"

export class PayoutApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
    this.name = "PayoutApiError"
  }
}

async function call<T>(path: string, init: RequestInit = {}, adminKey?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (adminKey) headers["X-Payout-Admin-Key"] = adminKey
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers, referrerPolicy: "no-referrer" })
  } catch {
    throw new PayoutApiError("Couldn't reach the server. Check your connection and try again.", 0)
  }
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new PayoutApiError(body.error || "Something went wrong. Try again.", res.status)
  }
  return body as T
}

// ── public (token in the body, never the URL) ──────────────────────────

export const payoutPublic = {
  dashboard: (token: string) =>
    call<CreatorDashboardData>("/api/creator/dashboard", { method: "POST", body: JSON.stringify({ token }) }),
  lookup: (token: string) =>
    call<PayoutPublicView>("/api/payout/lookup", { method: "POST", body: JSON.stringify({ token }) }),
  submit: (token: string, method: PayoutMethod, destination: string) =>
    call<PayoutSubmitResult>("/api/payout/submit", {
      method: "POST",
      body: JSON.stringify({ token, method, destination }),
    }),
}

// ── admin ──────────────────────────────────────────────────────────────

const enc = encodeURIComponent

export const payoutAdmin = {
  overview: (key: string) => call<PayoutAdminOverview>("/api/payouts/admin/creators", {}, key),
  events: (key: string, username: string) =>
    call<{ events: PayoutEvent[] }>(`/api/payouts/admin/creators/${enc(username)}/events`, {}, key),
  links: (key: string, usernames: string[]) =>
    call<{ links: PayoutLink[]; skipped: string[] }>(
      "/api/payouts/admin/links",
      { method: "POST", body: JSON.stringify({ usernames }) },
      key,
    ),
  rotate: (key: string, username: string) =>
    call<{ username: string; link: string }>(
      `/api/payouts/admin/creators/${enc(username)}/rotate-link`,
      { method: "POST" },
      key,
    ),
  queue: (key: string) => call<PaymentQueue>("/api/payouts/admin/queue", {}, key),
  markBooking: (key: string, row: Pick<QueueRow, "slug" | "username" | "platform">, action: BookingMarkAction, note = "") =>
    call<{ ok: true }>(
      "/api/payouts/admin/bookings/mark",
      { method: "POST", body: JSON.stringify({ ...row, action, note }) },
      key,
    ),
  setTrust: (key: string, username: string, override: QueueRow["trust_override"]) =>
    call<{ ok: true }>(
      `/api/payouts/admin/creators/${enc(username)}/trust`,
      { method: "POST", body: JSON.stringify({ override }) },
      key,
    ),
  clearFlag: (key: string, username: string) =>
    call<{ ok: true }>(`/api/payouts/admin/creators/${enc(username)}/clear-flag`, { method: "POST" }, key),
}

// The token lives in the URL fragment (/payout#<token>), which browsers never
// send to the server — so it can't land in access logs or Referer headers.
export function readTokenFromHash(): string {
  const token = window.location.hash.replace(/^#/, "").trim()
  return /^[A-Za-z0-9_-]{40,64}$/.test(token) ? token : ""
}

// Same wording as the scrape skill's dm_templates.json `payout.link`.
const DM_TEMPLATE =
  "hey twin drop your payment info here so i can get you paid as soon as your posts are up 🙂\n{link}"

export function dmFor(link: string): string {
  return DM_TEMPLATE.replace("{link}", link)
}

export function parseHandles(text: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of text.split(/[\s,]+/)) {
    const handle = raw.trim().replace(/^@/, "")
    const key = handle.toLowerCase()
    if (handle && !seen.has(key)) {
      seen.add(key)
      out.push(handle)
    }
  }
  return out
}
