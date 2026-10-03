import { useMemo, useState } from "react";
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AlertCircle, TrendingUp, TrendingDown } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "";

const TIER_COLORS = {
  elite: "#10b981",        // Green
  high_value: "#3b82f6",   // Blue
  solid: "#8b5cf6",        // Purple
  standard: "#f59e0b",     // Amber
  undervalued: "#06b6d4",  // Cyan
  overpriced: "#ef4444",   // Red
};

const TIER_LABELS = {
  elite: "Elite",
  high_value: "High Value",
  solid: "Solid",
  standard: "Standard",
  undervalued: "Undervalued",
  overpriced: "Overpriced",
};

interface EfficiencyMetrics {
  creator_username: string;
  total_campaigns: number;
  total_bookings: number;
  total_spend: number;
  total_views: number;
  total_engagement: number;
  // Unit-cost / ratio fields are null when the denominator was zero
  // (spend but no tracked views/engagement) — the API sends null instead
  // of Infinity, which isn't valid JSON.
  roi_ratio: number | null;
  cost_per_view: number | null;
  cost_per_engagement: number | null;
  engagement_rate: number | null;
  avg_post_rate: number | null;
  tier: string;
  pricing_gap_pct: number | null;
  last_booked: string;
  platform: string;
}

interface EfficiencyReport {
  report_date: string;
  analysis_period_days: number;
  total_creators_analyzed: number;
  total_campaigns: number;
  total_spend: number;
  total_views: number;
  total_engagement: number;
  avg_roi: number | null;
  median_roi: number | null;
  avg_cost_per_view: number | null;
  avg_cost_per_engagement: number | null;
  creators_by_tier: Record<string, number>;
  top_performers: EfficiencyMetrics[];
  undervalued_deals: EfficiencyMetrics[];
  overpriced_creators: EfficiencyMetrics[];
  efficiency_index: number;
  largest_efficiency_gaps: Array<{
    username: string;
    tier: string;
    pricing_gap_pct: number | null;
    avg_post_rate: number | null;
    roi_ratio: number | null;
  }>;
}

interface Insight {
  category: string;
  severity: string;
  finding: string;
  creators: string[];
  recommendation: string;
}

interface Recommendation {
  action: string;
  from: string[];
  to: string[];
  potential_uplift_views: number;
  projected_savings: number;
}

interface InsightsData {
  analysis_period_days: number;
  efficiency_index: number;
  key_findings: Insight[];
  recommendations: Recommendation[];
}

// Null-safe number formatting: metrics arrive as null when the unit cost
// is undefined (division by zero server-side). Render an em dash.
function fmt(v: number | null | undefined, f: (n: number) => string): string {
  return v == null ? "\u2014" : f(v);
}

export default function BookingEfficiency() {
  const [days, setDays] = useState(90);

  // Fetch efficiency report
  const { data: report, isLoading: reportLoading, isError: reportError, error: reportErrObj } = useQuery<EfficiencyReport>({
    queryKey: ["efficiency-report", days],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/efficiency/report?days=${days}`);
      if (!res.ok) throw new Error("Failed to fetch efficiency report");
      return res.json();
    },
  });

  // Fetch insights
  const { data: insights } = useQuery<InsightsData>({
    queryKey: ["efficiency-insights", days],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/efficiency/insights?days=${days}`);
      if (!res.ok) throw new Error("Failed to fetch insights");
      return res.json();
    },
  });

  // Prepare data for visualizations
  const tierData = useMemo(() => {
    if (!report) return [];
    return Object.entries(report.creators_by_tier).map(([tier, count]) => ({
      name: TIER_LABELS[tier as keyof typeof TIER_LABELS],
      value: count,
      fill: TIER_COLORS[tier as keyof typeof TIER_COLORS],
    }));
  }, [report]);

  const efficiencyGapData = useMemo(() => {
    if (!report) return [];
    return report.largest_efficiency_gaps
      .slice(0, 10)
      .map((g) => ({
        creator: g.username.substring(0, 15),
        gap: Math.abs(g.pricing_gap_pct ?? 0),
        roi: g.roi_ratio ?? 0,
        tier: g.tier,
      }));
  }, [report]);

  if (reportLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <p className="text-rt-fg-tertiary">Loading efficiency analysis...</p>
      </div>
    );
  }

  // CAMP-88: distinguish a fetch ERROR from genuinely-empty data — the old
  // code showed "No data available" for both, hiding real failures.
  if (reportError) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="mx-auto max-w-md rounded-xl border border-rt-red/30 bg-rt-red/10 px-4 py-4 text-center">
          <div className="flex items-center justify-center gap-2 text-rt-red">
            <AlertCircle size={18} />
            <span className="text-[14px] font-medium">Couldn't load efficiency report</span>
          </div>
          <div className="mt-1 text-[12px] text-rt-fg-tertiary">
            {reportErrObj instanceof Error ? reportErrObj.message : "The request failed — try again."}
          </div>
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="flex gap-2 text-rt-fg-tertiary">
          <AlertCircle size={20} />
          <p>No data available</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold">Booking Efficiency</h1>
          <p className="text-rt-fg-secondary">ROI analysis & creator valuation</p>
        </div>
        <Select value={days.toString()} onValueChange={(v) => setDays(parseInt(v))}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="30">Last 30 days</SelectItem>
            <SelectItem value="90">Last 90 days</SelectItem>
            <SelectItem value="180">Last 6 months</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-rt-fg-secondary">Efficiency Index</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{report.efficiency_index.toFixed(1)}</div>
            <p className="text-xs text-rt-fg-tertiary">Higher = better pricing alignment</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-rt-fg-secondary">Avg ROI</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{fmt(report.avg_roi, (n) => `${(n / 1000).toFixed(0)}K`)}</div>
            <p className="text-xs text-rt-fg-tertiary">views per dollar</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-rt-fg-secondary">Cost per View</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{fmt(report.avg_cost_per_view, (n) => `$${n.toFixed(4)}`)}</div>
            <p className="text-xs text-rt-fg-tertiary">average across all creators</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-rt-fg-secondary">Total Analyzed</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{report.total_creators_analyzed}</div>
            <p className="text-xs text-rt-fg-tertiary">creators in {report.total_campaigns} campaigns</p>
          </CardContent>
        </Card>
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Tier Distribution */}
        <Card>
          <CardHeader>
            <CardTitle>Creator Tier Distribution</CardTitle>
            <CardDescription>Count by efficiency tier</CardDescription>
          </CardHeader>
          <CardContent className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={tierData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }: { name?: string; value?: number }) => `${name}: ${value}`}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {tierData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Efficiency Gaps */}
        <Card>
          <CardHeader>
            <CardTitle>Top Pricing Gaps</CardTitle>
            <CardDescription>Creators with biggest price vs performance mismatches</CardDescription>
          </CardHeader>
          <CardContent className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={efficiencyGapData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="creator" angle={-45} textAnchor="end" height={60} />
                <YAxis />
                <Tooltip />
                <Bar dataKey="gap" fill="#ef4444" name="Pricing Gap %" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Performers Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Top Performers */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Elite Performers</CardTitle>
            <CardDescription>Highest ROI creators</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {report.top_performers.slice(0, 5).map((creator) => (
              <div key={creator.creator_username} className="flex items-start justify-between py-2 border-b">
                <div>
                  <p className="font-medium text-sm">{creator.creator_username}</p>
                  <p className="text-xs text-rt-fg-tertiary">{fmt(creator.avg_post_rate, (n) => `$${n.toFixed(0)}`)}/post</p>
                </div>
                <Badge className="bg-rt-green/15 text-rt-green">
                  {fmt(creator.roi_ratio, (n) => `${(n / 1000).toFixed(0)}K`)} ROI
                </Badge>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Undervalued Deals */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Undervalued Deals</CardTitle>
            <CardDescription>High performance, low cost</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {report.undervalued_deals.slice(0, 5).map((creator) => (
              <div key={creator.creator_username} className="flex items-start justify-between py-2 border-b">
                <div>
                  <p className="font-medium text-sm">{creator.creator_username}</p>
                  <p className="text-xs text-rt-fg-tertiary">{fmt(creator.avg_post_rate, (n) => `$${n.toFixed(0)}`)}/post</p>
                </div>
                <Badge className="bg-cyan-100 text-cyan-800">
                  {fmt(creator.pricing_gap_pct, (n) => (n * -1).toFixed(0))}% under
                </Badge>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Overpriced Creators */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Overpriced Creators</CardTitle>
            <CardDescription>High cost, lower ROI</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {report.overpriced_creators.slice(0, 5).map((creator) => (
              <div key={creator.creator_username} className="flex items-start justify-between py-2 border-b">
                <div>
                  <p className="font-medium text-sm">{creator.creator_username}</p>
                  <p className="text-xs text-rt-fg-tertiary">{fmt(creator.avg_post_rate, (n) => `$${n.toFixed(0)}`)}/post</p>
                </div>
                <Badge className="bg-rt-red/15 text-rt-red">
                  {fmt(creator.pricing_gap_pct, (n) => n.toFixed(0))}% over
                </Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Insights Section */}
      {insights && (
        <Tabs defaultValue="insights" className="w-full">
          <TabsList>
            <TabsTrigger value="insights">Key Findings</TabsTrigger>
            <TabsTrigger value="recommendations">Recommendations</TabsTrigger>
          </TabsList>

          <TabsContent value="insights" className="space-y-4">
            {insights.key_findings.length === 0 ? (
              <Card>
                <CardContent className="pt-6">
                  <p className="text-rt-fg-tertiary">No significant findings at this time.</p>
                </CardContent>
              </Card>
            ) : (
              insights.key_findings.map((finding, idx) => (
                <Card
                  key={idx}
                  className={
                    finding.severity === "high"
                      ? "border-rt-red/30 bg-rt-red/10"
                      : finding.severity === "medium"
                        ? "border-yellow-200 bg-yellow-50"
                        : "border-rt-purple/30 bg-rt-purple/10"
                  }
                >
                  <CardHeader>
                    <div className="flex items-start justify-between">
                      <div>
                        <CardTitle className="text-base">{finding.category}</CardTitle>
                        <CardDescription>{finding.finding}</CardDescription>
                      </div>
                      <Badge
                        variant={
                          finding.severity === "high" ? "destructive" : "secondary"
                        }
                      >
                        {finding.severity}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div>
                      <p className="text-sm font-medium">Affected creators:</p>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {finding.creators.slice(0, 5).map((creator) => (
                          <Badge key={creator} variant="outline">
                            {creator}
                          </Badge>
                        ))}
                        {finding.creators.length > 5 && (
                          <Badge variant="outline">+{finding.creators.length - 5}</Badge>
                        )}
                      </div>
                    </div>
                    <div>
                      <p className="text-sm font-medium">Recommendation:</p>
                      <p className="text-sm text-rt-fg-secondary mt-1">{finding.recommendation}</p>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </TabsContent>

          <TabsContent value="recommendations" className="space-y-4">
            {insights.recommendations.length === 0 ? (
              <Card>
                <CardContent className="pt-6">
                  <p className="text-rt-fg-tertiary">No optimization recommendations at this time.</p>
                </CardContent>
              </Card>
            ) : (
              insights.recommendations.map((rec, idx) => (
                <Card key={idx} className="border-rt-green/30 bg-rt-green/10">
                  <CardHeader>
                    <CardTitle className="text-base">{rec.action}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <p className="text-sm font-medium text-rt-fg-secondary">Reallocate from:</p>
                        <div className="flex flex-wrap gap-2 mt-2">
                          {rec.from.map((creator) => (
                            <Badge key={creator} variant="secondary">
                              {creator}
                            </Badge>
                          ))}
                        </div>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-rt-fg-secondary">Reallocate to:</p>
                        <div className="flex flex-wrap gap-2 mt-2">
                          {rec.to.map((creator) => (
                            <Badge key={creator} className="bg-green-600">
                              {creator}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    </div>
                    <div className="bg-rt-bg-card rounded p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <p className="text-sm text-rt-fg-secondary">Potential uplift:</p>
                        <p className="font-medium flex items-center gap-1">
                          <TrendingUp size={16} className="text-rt-green" />
                          {(rec.potential_uplift_views / 1000000).toFixed(1)}M views
                        </p>
                      </div>
                      <div className="flex items-center justify-between">
                        <p className="text-sm text-rt-fg-secondary">Projected savings:</p>
                        <p className="font-medium flex items-center gap-1">
                          <TrendingDown size={16} className="text-rt-green" />
                          ${rec.projected_savings.toFixed(0)}
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
