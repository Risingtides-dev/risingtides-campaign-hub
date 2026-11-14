import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import BookingEfficiency from "./BookingEfficiency"

vi.mock("recharts", () => {
  const Container = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>
  return Object.fromEntries([
    "BarChart", "Bar", "PieChart", "Pie", "Cell", "XAxis", "YAxis",
    "CartesianGrid", "Tooltip", "ResponsiveContainer",
  ].map((key) => [key, Container]))
})

const report = {
  report_date: "2026-11-13T21:00:00",
  analysis_period_days: 90,
  total_creators_analyzed: 0,
  total_campaigns: 0,
  total_spend: 0,
  total_views: 0,
  total_engagement: 0,
  avg_roi: null,
  median_roi: null,
  avg_cost_per_view: null,
  avg_cost_per_engagement: null,
  creators_by_tier: {},
  top_performers: [],
  undervalued_deals: [],
  overpriced_creators: [],
  efficiency_index: 0,
  largest_efficiency_gaps: [],
}

function show(reportStatus = 200, insightsStatus = 200) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const isReport = url.includes("/report?")
    const status = isReport ? reportStatus : insightsStatus
    return {
      ok: status === 200,
      status,
      json: async () => isReport ? report : {
        analysis_period_days: 90, efficiency_index: 0,
        key_findings: [], recommendations: [],
      },
    }
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><BookingEfficiency /></QueryClientProvider>)
}

describe("BookingEfficiency states", () => {
  beforeEach(() => vi.unstubAllGlobals())

  it("shows genuine empty cohorts and undefined costs without claiming free performance", async () => {
    show()
    expect(await screen.findByText("No discounted creators in this period.")).toBeInTheDocument()
    expect(screen.getByText("No overpriced creators in this period.")).toBeInTheDocument()
    expect(screen.getByText("No performers in this period.")).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "Analysis period" })).toBeInTheDocument()
    expect(screen.queryByText(/\$0\.0000/)).not.toBeInTheDocument()
  })

  it("keeps a successful report visible when insights fail and reports that failure", async () => {
    show(200, 503)
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load efficiency insights.")
    expect(screen.getByRole("heading", { name: "Booking Efficiency" })).toBeInTheDocument()
    expect(screen.queryByText("No significant findings at this time.")).not.toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "Key Findings" })).not.toBeInTheDocument()
  })

  it("reports a report failure instead of presenting an empty cohort", async () => {
    show(503)
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load efficiency report")
    expect(screen.queryByText("No performers in this period.")).not.toBeInTheDocument()
  })
})
