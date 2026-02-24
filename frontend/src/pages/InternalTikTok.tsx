import { useState, useCallback } from "react"
import {
  useInternalCreators,
  useInternalResults,
  useTriggerInternalScrape,
  useInternalScrapeStatus,
} from "@/lib/queries"
import { CreatorSidebar } from "@/components/internal/CreatorSidebar"
import { ScrapeProgress } from "@/components/internal/ScrapeProgress"
import { SongsResults } from "@/components/internal/SongsResults"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Loader2 } from "lucide-react"

export default function InternalTikTok() {
  const [hours, setHours] = useState(48)
  const [scraping, setScraping] = useState(false)

  // Data queries
  const { data: creators } = useInternalCreators()
  const { data: results, isLoading: resultsLoading } = useInternalResults()
  const triggerScrape = useTriggerInternalScrape()

  // Check if scrape is already running on mount
  const { data: scrapeStatus } = useInternalScrapeStatus(true)
  const isRunning = scraping || !!scrapeStatus?.running

  function handleScrape(e: React.FormEvent) {
    e.preventDefault()
    setScraping(true)
    triggerScrape.mutate(hours)
  }

  const handleScrapeComplete = useCallback(() => {
    setScraping(false)
  }, [])

  // Stat values
  const accountCount = creators?.length ?? 0
  const videosFound = results?.total_videos ?? 0
  const uniqueSongs = results?.unique_songs ?? 0

  // Format last scrape timestamp
  const lastScrapeRaw = results?.scraped_at
  let lastScrape = "Never"
  if (lastScrapeRaw) {
    const d = new Date(lastScrapeRaw)
    lastScrape = d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      timeZone: "America/New_York",
    }) + " " + d.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZone: "America/New_York",
    }) + " EST"
  }

  return (
    <div>
      {/* Top bar */}
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h1 className="text-[22px] font-semibold">Internal TikTok</h1>
          <p className="text-[#888] text-sm">
            Scrape internal creator accounts and see all sounds used
          </p>
        </div>
        <form
          onSubmit={handleScrape}
          className="flex items-center gap-2.5"
        >
          <label className="text-[13px] text-[#666]">Last</label>
          <Input
            type="number"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            min={1}
            max={720}
            className="w-[70px] text-center h-8 text-sm"
          />
          <label className="text-[13px] text-[#666]">hours</label>
          <Button
            type="submit"
            className="bg-[#0b62d6] hover:bg-[#0951b5] text-white"
            disabled={isRunning}
          >
            {isRunning ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Scraping...
              </>
            ) : (
              "Run Scrape"
            )}
          </Button>
        </form>
      </div>

      {/* Scrape progress */}
      <ScrapeProgress enabled={isRunning} onComplete={handleScrapeComplete} />

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        {[
          { label: "Accounts", value: accountCount.toString() },
          { label: "Last Scrape", value: lastScrape, small: true },
          { label: "Videos Found", value: videosFound.toString() },
          { label: "Unique Songs", value: uniqueSongs.toString() },
        ].map((card) => (
          <div
            key={card.label}
            className="bg-white border border-[#e8e8ef] rounded-[10px] p-4"
          >
            <div className="text-[#888] text-xs font-semibold uppercase tracking-wide mb-1">
              {card.label}
            </div>
            <div
              className={`font-bold text-[#1a1a2e] ${
                card.small ? "text-[16px]" : "text-[22px]"
              }`}
            >
              {card.value}
            </div>
          </div>
        ))}
      </div>

      {/* Last scrape details */}
      {results?.scraped_at && (
        <div className="mb-5 text-[13px] text-[#888] flex flex-wrap gap-x-4 gap-y-1">
          <span>{results.accounts_successful}/{results.accounts_total} accounts scraped</span>
          {results.accounts_failed > 0 && (
            <span className="text-red-500">{results.accounts_failed} failed</span>
          )}
          <span>{results.hours}h window</span>
        </div>
      )}

      {/* Two-column layout: sidebar + results */}
      <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-5 items-start">
        <CreatorSidebar />
        <SongsResults results={results} isLoading={resultsLoading} />
      </div>
    </div>
  )
}
