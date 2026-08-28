import type { CampaignBudget, CampaignStats } from "@/lib/types"

interface StatCardsProps {
  budget: CampaignBudget
  stats: CampaignStats
}

function formatCurrency(value: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })
}

function formatViews(value: number): string {
  if (!value) return "-"
  return value.toLocaleString("en-US")
}

function formatCpm(value: number | null): string {
  if (value === null || value === undefined) return "-"
  return `$${value.toFixed(2)}`
}

export function StatCards({ budget, stats }: StatCardsProps) {
  // Older cached payloads predate posts_expected; treat a missing value as
  // "unknown" so the card degrades to a plain count instead of "12 / 0".
  const expected = stats.posts_expected ?? 0
  const deliveredPct = expected
    ? Math.round((stats.live_posts / expected) * 100)
    : 0

  const cards = [
    {
      label: "Budget Used",
      value: `$${formatCurrency(budget.booked)}`,
      sub: `${budget.pct}% of $${formatCurrency(budget.total)}`,
    },
    {
      label: "Paid Out",
      value: `$${formatCurrency(budget.paid)}`,
      sub: `$${formatCurrency(budget.left)} remaining`,
    },
    {
      // Delivery against what was booked. A bare count of live posts can't
      // tell you whether a campaign is finished or barely started.
      label: "Posts Collected",
      value: expected
        ? `${stats.live_posts} / ${expected}`
        : stats.live_posts.toString(),
      sub: expected
        ? `${deliveredPct}% of ${expected} booked`
        : "no posts booked yet",
    },
    {
      label: "Total Views",
      value: formatViews(stats.total_views),
    },
    {
      label: "CPM",
      value: formatCpm(stats.cpm),
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="bg-rt-bg-card border border-white/8 rounded-[10px] p-4"
        >
          <div className="text-rt-fg-tertiary text-xs font-semibold uppercase tracking-wide mb-1">
            {card.label}
          </div>
          <div className="text-[22px] font-bold text-rt-fg">{card.value}</div>
          {card.sub && (
            <div className="text-rt-fg-tertiary text-[13px] mt-0.5">{card.sub}</div>
          )}
        </div>
      ))}
    </div>
  )
}
