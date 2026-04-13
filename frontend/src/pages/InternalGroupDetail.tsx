import { useState, useCallback } from "react"
import { useParams, Link } from "react-router-dom"
import {
  useInternalGroup,
  useInternalGroupStats,
  useInternalCreators,
  useTriggerGroupScrape,
  useInternalScrapeStatus,
} from "@/lib/queries"
import { ScrapeProgress } from "@/components/internal/ScrapeProgress"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Loader2, ArrowLeft } from "lucide-react"

export default function InternalGroupDetail() {
  const { slug } = useParams<{ slug: string }>()
  const { data: group, isLoading: groupLoading } = useInternalGroup(slug || "")
  const { data: allCreators } = useInternalCreators()
  const [days, setDays] = useState(30)
  const { data: stats, isLoading: statsLoading } = useInternalGroupStats(slug || "", days)
  const scrape = useTriggerGroupScrape()
  const { data: scrapeStatus } = useInternalScrapeStatus(true)
  const [scraping, setScraping] = useState(false)
  const isRunning = scraping || !!scrapeStatus?.running

  // Build a map of username -> creator data for video/view counts
  const creatorMap = new Map<string, { total_videos: number; total_views: number }>()
  for (const c of allCreators || []) {
    creatorMap.set(c.username.toLowerCase(), c)
  }

  function handleScrapeGroup() {
    setScraping(true)
    scrape.mutate({ group: slug })
  }

  const handleScrapeComplete = useCallback(() => setScraping(false), [])

  if (groupLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="size-6 animate-spin text-[#888]" />
      </div>
    )
  }

  if (!group) {
    return <p className="text-center text-[#888] py-20">Group not found.</p>
  }

  const members = group.members || []

  // Sort members by stats views if available
  const sortedMembers = [...members].sort((a, b) => {
    const aStats = stats?.creators?.find((c) => c.username === a.toLowerCase())
    const bStats = stats?.creators?.find((c) => c.username === b.toLowerCase())
    return (bStats?.views ?? 0) - (aStats?.views ?? 0)
  })

  return (
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <Link to="/internal" className="text-[#0b62d6] text-sm hover:underline flex items-center gap-1 mb-1">
            <ArrowLeft className="size-3.5" /> Internal TikTok
          </Link>
          <h1 className="text-[22px] font-semibold">{group.title}</h1>
          <p className="text-[#888] text-sm">
            {group.member_count} accounts &middot; {group.kind}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[13px] text-[#666]">Last</label>
          <Input
            type="number"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            min={1}
            max={365}
            className="w-[60px] text-center h-8 text-sm"
          />
          <label className="text-[13px] text-[#666]">days</label>
          <Button
            onClick={handleScrapeGroup}
            className="bg-[#0b62d6] hover:bg-[#0951b5] text-white"
            disabled={isRunning}
          >
            {isRunning ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Scraping...
              </>
            ) : (
              "Scrape Group"
            )}
          </Button>
        </div>
      </div>

      {/* Scrape progress */}
      <ScrapeProgress enabled={isRunning} onComplete={handleScrapeComplete} />

      {/* Stat cards */}
      {statsLoading ? (
        <div className="flex items-center gap-2 text-[#888] text-xs mb-5">
          <Loader2 className="size-3 animate-spin" /> Loading stats...
        </div>
      ) : stats ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
          {[
            { label: "Accounts", value: group.member_count.toString() },
            { label: `Posts (${days}d)`, value: stats.total_posts.toString() },
            { label: "Total Views", value: stats.total_views.toLocaleString() },
            { label: "Total Likes", value: stats.total_likes.toLocaleString() },
          ].map((card) => (
            <div key={card.label} className="bg-white border border-[#e8e8ef] rounded-[10px] p-4">
              <div className="text-[#888] text-xs font-semibold uppercase tracking-wide mb-1">{card.label}</div>
              <div className="font-bold text-[#1a1a2e] text-[22px]">{card.value}</div>
            </div>
          ))}
        </div>
      ) : null}

      {/* Creators table */}
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden mb-5">
        <div className="px-4 py-3 border-b border-[#e8e8ef]">
          <h3 className="text-[15px] font-semibold">Creators</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#e8e8ef] bg-[#f8f8fc]">
              <th className="text-left px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Creator</th>
              <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Posts ({days}d)</th>
              <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Views ({days}d)</th>
              <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Likes ({days}d)</th>
              <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">All-time Videos</th>
            </tr>
          </thead>
          <tbody>
            {sortedMembers.map((username) => {
              const creatorStats = stats?.creators?.find((c) => c.username === username.toLowerCase())
              const allTime = creatorMap.get(username.toLowerCase())
              return (
                <tr key={username} className="border-b border-[#f0f0f5] last:border-b-0 hover:bg-[#f8f8fc]">
                  <td className="px-4 py-2.5">
                    <Link to={`/internal/${username}`} className="text-[#0b62d6] hover:underline">
                      @{username}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 text-right text-[#666]">{creatorStats?.posts ?? 0}</td>
                  <td className="px-4 py-2.5 text-right text-[#666]">{(creatorStats?.views ?? 0).toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-right text-[#666]">{(creatorStats?.likes ?? 0).toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-right text-[#444]">{allTime?.total_videos ?? 0}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Top Songs */}
      {stats?.top_songs && stats.top_songs.length > 0 && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden">
          <div className="px-4 py-3 border-b border-[#e8e8ef]">
            <h3 className="text-[15px] font-semibold">Top Songs ({days}d)</h3>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#e8e8ef] bg-[#f8f8fc]">
                <th className="text-left px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Song</th>
                <th className="text-left px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Artist</th>
                <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Posts</th>
                <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Views</th>
              </tr>
            </thead>
            <tbody>
              {stats.top_songs.map((song, i) => (
                <tr key={i} className="border-b border-[#f0f0f5] last:border-b-0">
                  <td className="px-4 py-2.5 text-[#1a1a2e]">{song.song || "Unknown"}</td>
                  <td className="px-4 py-2.5 text-[#666]">{song.artist || "Unknown"}</td>
                  <td className="px-4 py-2.5 text-right text-[#666]">{song.posts}</td>
                  <td className="px-4 py-2.5 text-right text-[#666]">{song.views.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
