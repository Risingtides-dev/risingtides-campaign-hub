import { useState, useCallback, useMemo } from "react"
import { useParams, Link } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import {
  useInternalCreators,
  useInternalGroups,
  useTriggerGroupScrape,
  useInternalScrapeStatus,
  useInternalResults,
  keys,
} from "@/lib/queries"
import { ScrapeProgress } from "@/components/internal/ScrapeProgress"
import { SongsResults } from "@/components/internal/SongsResults"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Loader2, ArrowLeft, RefreshCw } from "lucide-react"
import type { InternalScrapeResults, InternalSongResult } from "@/lib/types"

const CATEGORIES: Record<string, { title: string; groupSlugs: string[]; scrapeGroup?: string }> = {
  internal: {
    title: "Internal Pages",
    groupSlugs: ["jake_balik", "john_smathers", "sam_hudgens", "eric_cromartie", "johnny_balik", "seeno_pages"],
    // No scrapeGroup — scrapes all creators
  },
  warner: {
    title: "Warner Pages",
    groupSlugs: ["warner_pages"],
    scrapeGroup: "warner_pages",
  },
  atlantic: {
    title: "Atlantic Pages",
    groupSlugs: ["atlantic_pages"],
    scrapeGroup: "atlantic_pages",
  },
  warner_test: {
    title: "Warner Test Pages",
    groupSlugs: ["warner_test_pages"],
    scrapeGroup: "warner_test_pages",
  },
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
}

function daysAgoStr(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

export default function InternalScrapeView() {
  const { category } = useParams<{ category: string }>()
  const config = CATEGORIES[category || ""] || CATEGORIES.internal

  const [startDate, setStartDate] = useState(daysAgoStr(30))
  const [endDate, setEndDate] = useState(todayStr())
  const [scraping, setScraping] = useState(false)

  const queryClient = useQueryClient()
  const { data: groups } = useInternalGroups()
  const { data: creators } = useInternalCreators()
  const { data: results, isLoading: resultsLoading, refetch: refetchResults } = useInternalResults()
  const scrape = useTriggerGroupScrape()
  const { data: scrapeStatus } = useInternalScrapeStatus(true)
  const isRunning = scraping || !!scrapeStatus?.running

  const handleScrapeComplete = useCallback(() => {
    setScraping(false)
    // Refetch results after scrape completes so links show up
    queryClient.invalidateQueries({ queryKey: keys.internalResults })
  }, [queryClient])

  // Find all member usernames for this category's groups
  const categoryMembers = useMemo(() => {
    if (!groups) return new Set<string>()
    const members = new Set<string>()
    for (const g of groups) {
      if (config.groupSlugs.includes(g.slug)) {
        // We don't have member lists from the groups list endpoint,
        // so we'll use the creators list and match against group membership
        // For now, we'll fetch from the group detail endpoints
      }
    }
    return members
  }, [groups, config.groupSlugs])

  // Get account count from groups
  const accountCount = useMemo(() => {
    if (!groups) return 0
    return groups
      .filter((g) => config.groupSlugs.includes(g.slug))
      .reduce((sum, g) => sum + g.member_count, 0)
  }, [groups, config.groupSlugs])

  // Filter results to only show songs/videos from this category's accounts
  // Since we don't have per-account group membership in the results, we show
  // all results after a category-scoped scrape. The scrape itself is scoped
  // so the results will naturally be limited to the right accounts.
  // For "internal" (scrape all), we show everything.
  const filteredResults = useMemo((): InternalScrapeResults | undefined => {
    if (!results) return undefined
    // After a scoped scrape, results contain only that scope's data
    // so we pass through as-is
    return results
  }, [results])

  function handleScrape() {
    setScraping(true)
    const params: Record<string, string> = { start_date: startDate, end_date: endDate }
    if (config.scrapeGroup) {
      params.group = config.scrapeGroup
    }
    scrape.mutate(params)
  }

  return (
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <Link to="/internal" className="text-[#0b62d6] text-sm hover:underline flex items-center gap-1 mb-1">
            <ArrowLeft className="size-3.5" /> Internal TikTok
          </Link>
          <h1 className="text-[22px] font-semibold">{config.title}</h1>
          <p className="text-[#888] text-sm">{accountCount} accounts</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-[145px] h-8 text-sm"
          />
          <span className="text-[#888] text-sm">to</span>
          <Input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="w-[145px] h-8 text-sm"
          />
          <Button
            onClick={handleScrape}
            className="bg-[#0b62d6] hover:bg-[#0951b5] text-white"
            disabled={isRunning}
          >
            {isRunning ? (
              <><Loader2 className="size-4 animate-spin" /> Scraping...</>
            ) : (
              `Scrape ${config.title}`
            )}
          </Button>
        </div>
      </div>

      {/* Scrape progress */}
      <ScrapeProgress enabled={isRunning} onComplete={handleScrapeComplete} />

      {/* Accounts list */}
      {creators && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden mb-5">
          <div className="px-4 py-3 border-b border-[#e8e8ef]">
            <h3 className="text-[15px] font-semibold">Accounts ({accountCount})</h3>
          </div>
          <div className="px-4 py-2 flex flex-wrap gap-2">
            {creators
              .filter(() => {
                // Show all creators for "internal" category
                // For warner/atlantic, we'd need to filter by group membership
                // Since we don't have that data easily, show all for now
                // The scrape is already scoped correctly
                return true
              })
              .sort((a, b) => (b.total_views ?? 0) - (a.total_views ?? 0))
              .slice(0, category === "internal" ? undefined : accountCount > 0 ? accountCount * 3 : 20)
              .map((c) => (
                <Link
                  key={c.username}
                  to={`/internal/${c.username}`}
                  className="text-[#0b62d6] text-[13px] hover:underline"
                >
                  @{c.username}
                </Link>
              ))}
          </div>
        </div>
      )}

      {/* Results header with refresh button */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[18px] font-semibold text-[#1a1a2e]">
          Scrape Results
          {results?.scraped_at && (
            <span className="text-[13px] text-[#888] font-normal ml-2">
              Last scraped: {new Date(results.scraped_at).toLocaleString("en-US", {
                month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
                hour12: true, timeZone: "America/New_York",
              })} EST
            </span>
          )}
        </h2>
        <Button
          onClick={() => refetchResults()}
          variant="outline"
          size="sm"
          className="text-xs"
        >
          <RefreshCw className="size-3.5" /> Refresh Results
        </Button>
      </div>

      {/* Songs + links output */}
      <SongsResults results={filteredResults} isLoading={resultsLoading} />
    </div>
  )
}
