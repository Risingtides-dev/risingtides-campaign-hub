import { useState } from "react"
import { money } from "@/lib/payouts"
import type { CreatorBookingCard } from "@/lib/payouts"

const STATUS: Record<CreatorBookingCard["status"], { label: string; cls: string }> = {
  in_progress: { label: "In progress", cls: "bg-white/5 text-rt-fg-secondary" },
  complete: { label: "All posts in — payment coming", cls: "bg-rt-green/10 text-rt-green" },
  paid: { label: "Paid", cls: "bg-rt-green/10 text-rt-green" },
}

// Sound links are typed by staff; only ever render real https links.
const isSafeUrl = (url: string) => /^https:\/\//i.test(url)

const PLATFORM_LABEL: Record<string, string> = { tiktok: "TikTok", instagram: "Instagram" }


function CopyLine({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <li className="flex items-start justify-between gap-3 rounded-md bg-rt-bg-black px-3 py-2">
      <span className="text-sm text-rt-fg whitespace-pre-wrap break-words">{text}</span>
      <button
        type="button"
        className="shrink-0 text-xs text-rt-magenta"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          } catch {
            /* clipboard blocked: the text is still selectable */
          }
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </li>
  )
}

export function BookingCard({ card }: { card: CreatorBookingCard }) {
  const status = STATUS[card.status]
  const pct = card.posts_owed ? Math.min(100, Math.round((card.posts_done / card.posts_owed) * 100)) : 0
  return (
    <article className="rounded-xl bg-rt-bg-card border border-white/8 p-5 space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold text-rt-fg">{card.campaign}</h3>
          <p className="text-xs text-rt-fg-tertiary">
            {card.platforms.map((p) => PLATFORM_LABEL[p] ?? p).join(" + ")} · {money(card.rate)}
          </p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs ${status.cls}`}>{status.label}</span>
      </header>

      <div>
        <div className="flex justify-between text-xs text-rt-fg-tertiary mb-1">
          <span>Posts</span>
          <span>
            {card.posts_done} / {card.posts_owed} posted
          </span>
        </div>
        <div className="h-2 rounded-full bg-white/5 overflow-hidden">
          <div className="h-full bg-rt-magenta" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {card.sounds.some((s) => isSafeUrl(s.url)) && (
        <div className="flex flex-wrap gap-2">
          {card.sounds.filter((s) => isSafeUrl(s.url)).map((s) => (
            <a
              key={s.url}
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-md border border-rt-magenta/50 px-3 py-2 text-sm text-rt-fg hover:bg-rt-magenta/10"
            >
              Use this sound · {PLATFORM_LABEL[s.platform] ?? s.platform} ↗
            </a>
          ))}
        </div>
      )}

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wider text-rt-fg-tertiary mb-1">Brief</h4>
        <p className={`text-sm whitespace-pre-wrap ${card.open_creative ? "text-rt-fg-secondary italic" : "text-rt-fg"}`}>
          {card.brief}
        </p>
      </div>

      {card.captions.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-rt-fg-tertiary mb-1">
            Text on screen ideas
          </h4>
          <ul className="space-y-1.5">
            {card.captions.map((c, i) => (
              <CopyLine key={`${i}-${c}`} text={c} />
            ))}
          </ul>
        </div>
      )}
    </article>
  )
}
