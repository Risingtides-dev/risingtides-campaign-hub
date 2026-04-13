import { useState, useCallback } from "react"
import { Link } from "react-router-dom"
import {
  useInternalCreators,
  useInternalGroups,
  useInternalGroupStats,
  useTriggerInternalScrape,
  useTriggerGroupScrape,
  useInternalScrapeStatus,
} from "@/lib/queries"
import { ScrapeProgress } from "@/components/internal/ScrapeProgress"
import { Button } from "@/components/ui/button"
import { Loader2, ChevronRight } from "lucide-react"
import type { InternalGroup } from "@/lib/types"

function GroupCard({ group }: { group: InternalGroup }) {
  const { data: stats, isLoading } = useInternalGroupStats(group.slug, 30)
  const scrape = useTriggerGroupScrape()

  function handleScrape(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    scrape.mutate({ group: group.slug })
  }

  return (
    <Link
      to={`/internal/group/${group.slug}`}
      className="block bg-white border border-[#e8e8ef] rounded-[10px] p-5 hover:border-[#0b62d6]/40 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-[16px] font-semibold text-[#1a1a2e]">{group.title}</h3>
          <p className="text-[12px] text-[#888]">{group.member_count} accounts</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={handleScrape}
            disabled={scrape.isPending}
            className="bg-[#0b62d6] hover:bg-[#0951b5] text-white text-xs h-7 px-2.5"
          >
            {scrape.isPending ? <Loader2 className="size-3 animate-spin" /> : "Scrape"}
          </Button>
          <ChevronRight className="size-4 text-[#888]" />
        </div>
      </div>
      {isLoading ? (
        <div className="flex items-center gap-2 text-[#888] text-xs">
          <Loader2 className="size-3 animate-spin" /> Loading stats...
        </div>
      ) : stats ? (
        <div className="grid grid-cols-3 gap-3">
          <div>
            <div className="text-[11px] text-[#888] uppercase tracking-wide">Views</div>
            <div className="text-[18px] font-bold text-[#1a1a2e]">
              {stats.total_views >= 1_000_000
                ? `${(stats.total_views / 1_000_000).toFixed(1)}M`
                : stats.total_views >= 1_000
                ? `${(stats.total_views / 1_000).toFixed(1)}K`
                : stats.total_views.toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-[#888] uppercase tracking-wide">Posts</div>
            <div className="text-[18px] font-bold text-[#1a1a2e]">{stats.total_posts}</div>
          </div>
          <div>
            <div className="text-[11px] text-[#888] uppercase tracking-wide">Likes</div>
            <div className="text-[18px] font-bold text-[#1a1a2e]">
              {stats.total_likes >= 1_000_000
                ? `${(stats.total_likes / 1_000_000).toFixed(1)}M`
                : stats.total_likes >= 1_000
                ? `${(stats.total_likes / 1_000).toFixed(1)}K`
                : stats.total_likes.toLocaleString()}
            </div>
          </div>
        </div>
      ) : null}
    </Link>
  )
}

export default function InternalTikTok() {
  const [tab, setTab] = useState<"groups" | "creators">("groups")
  const [scraping, setScraping] = useState(false)

  const { data: groups, isLoading: groupsLoading } = useInternalGroups()
  const { data: creators, isLoading: creatorsLoading } = useInternalCreators()
  const triggerScrape = useTriggerInternalScrape()
  const { data: scrapeStatus } = useInternalScrapeStatus(true)
  const isRunning = scraping || !!scrapeStatus?.running

  const sortedGroups = [...(groups || [])]
    .filter((g) => g.member_count > 0)
    .sort((a, b) => (a.sort_order ?? 99) - (b.sort_order ?? 99))

  const sortedCreators = [...(creators || [])].sort(
    (a, b) => (b.total_views ?? 0) - (a.total_views ?? 0)
  )

  function handleScrapeAll(e: React.FormEvent) {
    e.preventDefault()
    setScraping(true)
    triggerScrape.mutate(48)
  }

  const handleScrapeComplete = useCallback(() => {
    setScraping(false)
  }, [])

  return (
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h1 className="text-[22px] font-semibold">Internal TikTok</h1>
          <p className="text-[#888] text-sm">
            {sortedGroups.length} groups &middot; {creators?.length ?? 0} accounts
          </p>
        </div>
        <Button
          onClick={handleScrapeAll}
          className="bg-[#0b62d6] hover:bg-[#0951b5] text-white"
          disabled={isRunning}
        >
          {isRunning ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Scraping...
            </>
          ) : (
            "Scrape All"
          )}
        </Button>
      </div>

      {/* Scrape progress */}
      <ScrapeProgress
        enabled={isRunning}
        onComplete={handleScrapeComplete}
      />

      {/* Tabs */}
      <div className="flex gap-1 mb-5 border-b border-[#e8e8ef]">
        <button
          type="button"
          onClick={() => setTab("groups")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "groups"
              ? "border-[#0b62d6] text-[#0b62d6]"
              : "border-transparent text-[#888] hover:text-[#1a1a2e]"
          }`}
        >
          Groups
        </button>
        <button
          type="button"
          onClick={() => setTab("creators")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "creators"
              ? "border-[#0b62d6] text-[#0b62d6]"
              : "border-transparent text-[#888] hover:text-[#1a1a2e]"
          }`}
        >
          All Creators ({creators?.length ?? 0})
        </button>
      </div>

      {/* Groups tab */}
      {tab === "groups" && (
        <div>
          {groupsLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="size-5 animate-spin text-[#888]" />
            </div>
          )}
          {!groupsLoading && sortedGroups.length === 0 && (
            <p className="text-[#888] text-sm text-center py-12">No groups found.</p>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {sortedGroups.map((group) => (
              <GroupCard key={group.slug} group={group} />
            ))}
          </div>
        </div>
      )}

      {/* All Creators tab */}
      {tab === "creators" && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden">
          {creatorsLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="size-5 animate-spin text-[#888]" />
            </div>
          )}
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#e8e8ef] bg-[#f8f8fc]">
                <th className="text-left px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Creator</th>
                <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Videos</th>
                <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Views</th>
              </tr>
            </thead>
            <tbody>
              {sortedCreators.map((c) => (
                <tr key={c.username} className="border-b border-[#f0f0f5] last:border-b-0 hover:bg-[#f8f8fc]">
                  <td className="px-4 py-2">
                    <Link to={`/internal/${c.username}`} className="text-[#0b62d6] hover:underline">
                      @{c.username}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-right text-[#666]">{c.total_videos}</td>
                  <td className="px-4 py-2 text-right text-[#666]">{c.total_views.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
