import { useState, useCallback, useMemo } from "react"
import { useParams, Link } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import {
  useInternalGroup,
  useInternalGroupStats,
  useInternalCreators,
  useTriggerGroupScrape,
  useInternalScrapeStatus,
  useInternalResults,
  keys,
} from "@/lib/queries"
import { ScrapeProgress } from "@/components/internal/ScrapeProgress"
import { SongsResults } from "@/components/internal/SongsResults"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Loader2, ArrowLeft, X, Plus, RefreshCw } from "lucide-react"

function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
}

function daysAgoStr(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

function daysBetween(start: string, end: string): number {
  const s = new Date(start)
  const e = new Date(end)
  return Math.max(1, Math.round((e.getTime() - s.getTime()) / (1000 * 60 * 60 * 24)))
}

export default function InternalGroupDetail() {
  const { slug } = useParams<{ slug: string }>()
  const { data: group, isLoading: groupLoading } = useInternalGroup(slug || "")
  const { data: allCreators } = useInternalCreators()

  const [startDate, setStartDate] = useState(daysAgoStr(30))
  const [endDate, setEndDate] = useState(todayStr())
  const [memberInput, setMemberInput] = useState("")

  const days = useMemo(() => daysBetween(startDate, endDate), [startDate, endDate])
  const { data: stats, isLoading: statsLoading } = useInternalGroupStats(slug || "", days)

  const queryClient = useQueryClient()
  const scrape = useTriggerGroupScrape()
  const { data: scrapeStatus } = useInternalScrapeStatus(true)
  const { data: results, isLoading: resultsLoading, refetch: refetchResults } = useInternalResults()
  const [scraping, setScraping] = useState(false)
  const isRunning = scraping || !!scrapeStatus?.running

  const creatorMap = new Map<string, { total_videos: number; total_views: number }>()
  for (const c of allCreators || []) {
    creatorMap.set(c.username.toLowerCase(), c)
  }

  function handleScrapeGroup() {
    setScraping(true)
    scrape.mutate({ group: slug, start_date: startDate, end_date: endDate })
  }

  const handleScrapeComplete = useCallback(() => {
    setScraping(false)
    queryClient.invalidateQueries({ queryKey: keys.internalResults })
  }, [queryClient])

  async function handleAddMembers(e: React.FormEvent) {
    e.preventDefault()
    const value = memberInput.trim()
    if (!value || !group) return
    try {
      await fetch(`/api/internal/groups/${group.id}/members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ usernames: value }),
      })
      setMemberInput("")
      window.location.reload()
    } catch {
      // Silently handle — user can retry
    }
  }

  async function handleRemoveMember(username: string) {
    if (!group) return
    if (!confirm(`Remove @${username} from ${group.title}?`)) return
    try {
      await fetch(`/api/internal/groups/${group.id}/members/${username}`, {
        method: "DELETE",
      })
      window.location.reload()
    } catch {
      // Silently handle — user can retry
    }
  }

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
            onClick={handleScrapeGroup}
            className="bg-[#0b62d6] hover:bg-[#0951b5] text-white"
            disabled={isRunning}
            size="sm"
          >
            {isRunning ? (
              <><Loader2 className="size-3.5 animate-spin" /> Scraping...</>
            ) : (
              "Scrape Group"
            )}
          </Button>
        </div>
      </div>

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
            { label: "Posts", value: stats.total_posts.toString() },
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

      {/* Add members form */}
      <form onSubmit={handleAddMembers} className="mb-4 flex gap-2">
        <Input
          type="text"
          value={memberInput}
          onChange={(e) => setMemberInput(e.target.value)}
          placeholder="Add members (@username, comma separated)"
          className="flex-1 text-sm h-9"
        />
        <Button type="submit" size="sm" className="bg-[#0b62d6] hover:bg-[#0951b5] text-white h-9 px-4">
          <Plus className="size-3.5" /> Add
        </Button>
      </form>

      {/* Creators table */}
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden mb-5">
        <div className="px-4 py-3 border-b border-[#e8e8ef]">
          <h3 className="text-[15px] font-semibold">Creators</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#e8e8ef] bg-[#f8f8fc]">
              <th className="text-left px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Creator</th>
              <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Posts</th>
              <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Views</th>
              <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Likes</th>
              <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">All-time</th>
              <th className="w-10"></th>
            </tr>
          </thead>
          <tbody>
            {sortedMembers.map((username) => {
              const cStats = stats?.creators?.find((c) => c.username === username.toLowerCase())
              const allTime = creatorMap.get(username.toLowerCase())
              return (
                <tr key={username} className="border-b border-[#f0f0f5] last:border-b-0 hover:bg-[#f8f8fc]">
                  <td className="px-4 py-2.5">
                    <Link to={`/internal/${username}`} className="text-[#0b62d6] hover:underline">@{username}</Link>
                  </td>
                  <td className="px-4 py-2.5 text-right text-[#666]">{cStats?.posts ?? 0}</td>
                  <td className="px-4 py-2.5 text-right text-[#666]">{(cStats?.views ?? 0).toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-right text-[#666]">{(cStats?.likes ?? 0).toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-right text-[#444]">{allTime?.total_videos ?? 0} videos</td>
                  <td className="px-2 py-2.5">
                    <button
                      type="button"
                      onClick={() => handleRemoveMember(username)}
                      className="text-red-400 hover:text-red-600 p-1"
                      title="Remove from group"
                    >
                      <X className="size-3.5" />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Top Songs */}
      {stats?.top_songs && stats.top_songs.length > 0 && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden mb-5">
          <div className="px-4 py-3 border-b border-[#e8e8ef]">
            <h3 className="text-[15px] font-semibold">Top Songs</h3>
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

      {/* Scrape results — copy/paste links for Cobrand */}
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
      <SongsResults results={results} isLoading={resultsLoading} />
    </div>
  )
}
