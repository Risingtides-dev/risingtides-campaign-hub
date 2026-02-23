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
      label: "Live Posts",
      value: stats.live_posts.toString(),
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
          className="bg-white border border-[#e8e8ef] rounded-[10px] p-4"
        >
          <div className="text-[#888] text-xs font-semibold uppercase tracking-wide mb-1">
            {card.label}
          </div>
          <div className="text-[22px] font-bold text-[#1a1a2e]">{card.value}</div>
          {card.sub && (
            <div className="text-[#888] text-[13px] mt-0.5">{card.sub}</div>
          )}
        </div>
      ))}
    </div>
  )
}
