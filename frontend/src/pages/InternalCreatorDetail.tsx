import { useState } from "react"
import { useParams, Link } from "react-router-dom"
import { useInternalCreator } from "@/lib/queries"
import { Button } from "@/components/ui/button"
import {
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  Loader2,
  ExternalLink,
} from "lucide-react"
import type { InternalSongResult } from "@/lib/types"

// ---- Creator Song Card ----

function CreatorSongCard({ song }: { song: InternalSongResult }) {
  const [linksOpen, setLinksOpen] = useState(false)
  const [tableOpen, setTableOpen] = useState(song.videos.length <= 5)
  const [copied, setCopied] = useState(false)

  const linksText = song.videos.map((v) => v.url).join("\n")

  async function copyLinks() {
    await navigator.clipboard.writeText(linksText)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  function formatDate(dateStr: string | undefined): string {
    if (!dateStr) return "\u2014"
    // Handle YYYYMMDD format
    if (dateStr.length === 8 && !dateStr.includes("-")) {
      return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6)}`
    }
    return dateStr
  }

  return (
    <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-4 mb-2.5">
      {/* Song header */}
      <div className="flex justify-between items-start">
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold text-rt-fg truncate">
            {song.song}
          </div>
          <div className="text-rt-fg-tertiary text-[13px]">{song.artist}</div>
        </div>
        <div className="text-right flex-shrink-0 ml-4">
          <div className="text-[18px] font-bold text-rt-fg">
            {song.total_views.toLocaleString()}
          </div>
          <div className="text-rt-fg-tertiary text-[13px]">
            {song.videos.length} post{song.videos.length !== 1 ? "s" : ""}{" "}
            &middot; {song.total_likes.toLocaleString()} likes
          </div>
        </div>
      </div>

      {/* Video table (auto-shown for <= 5, expandable for > 5) */}
      {song.videos.length > 5 && !tableOpen ? (
        <button
          type="button"
          onClick={() => setTableOpen(true)}
          className="mt-2 flex items-center gap-1 text-[13px] text-rt-magenta font-medium hover:underline"
        >
          Show {song.videos.length} videos
          <ChevronDown className="size-3.5" />
        </button>
      ) : null}

      {(song.videos.length <= 5 || tableOpen) && (
        <div className="mt-2 overflow-x-auto">
          {song.videos.length > 5 && (
            <button
              type="button"
              onClick={() => setTableOpen(false)}
              className="mb-1.5 flex items-center gap-1 text-[13px] text-rt-magenta font-medium hover:underline"
            >
              Hide videos
              <ChevronUp className="size-3.5" />
            </button>
          )}
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-white/5">
                <th className="text-[11px] text-rt-fg-tertiary font-semibold uppercase tracking-wide px-2.5 py-1.5">
                  Views
                </th>
                <th className="text-[11px] text-rt-fg-tertiary font-semibold uppercase tracking-wide px-2.5 py-1.5">
                  Likes
                </th>
                <th className="text-[11px] text-rt-fg-tertiary font-semibold uppercase tracking-wide px-2.5 py-1.5">
                  Date
                </th>
                <th className="text-[11px] text-rt-fg-tertiary font-semibold uppercase tracking-wide px-2.5 py-1.5">
                  Link
                </th>
              </tr>
            </thead>
            <tbody>
              {song.videos.map((v, vi) => (
                <tr
                  key={vi}
                  className="border-b border-white/5 last:border-b-0"
                >
                  <td className="px-2.5 py-1 text-[13px]">
                    {v.views.toLocaleString()}
                  </td>
                  <td className="px-2.5 py-1 text-[13px]">
                    {v.likes.toLocaleString()}
                  </td>
                  <td className="px-2.5 py-1 text-[13px] text-rt-fg-tertiary">
                    {formatDate(v.upload_date)}
                  </td>
                  <td className="px-2.5 py-1 text-[13px]">
                    <a
                      href={v.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-rt-magenta hover:underline"
                    >
                      Open
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Copy links */}
      <div className="mt-2">
        <button
          type="button"
          onClick={() => setLinksOpen(!linksOpen)}
          className="flex items-center gap-1 text-[12px] text-rt-fg-tertiary hover:text-rt-fg"
        >
          Copy links
          {linksOpen ? (
            <ChevronUp className="size-3" />
          ) : (
            <ChevronDown className="size-3" />
          )}
        </button>
        {linksOpen && (
          <div className="relative mt-1">
            <textarea
              readOnly
              value={linksText}
              className="w-full font-mono text-[11px] p-1.5 border border-white/10 rounded-md bg-white/[0.03] resize-y"
              style={{
                height: `${Math.max(50, song.videos.length * 20)}px`,
                maxHeight: "150px",
              }}
            />
            <Button
              type="button"
              variant="outline"
              size="xs"
              className="absolute top-1 right-1 text-[11px]"
              onClick={copyLinks}
            >
              {copied ? (
                <>
                  <Check className="size-3" /> Copied
                </>
              ) : (
                <>
                  <Copy className="size-3" /> Copy
                </>
              )}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}

// ---- Main Page ----

export default function InternalCreatorDetail() {
  const { username } = useParams<{ username: string }>()
  const { data, isLoading, isError, error } = useInternalCreator(username!)

  // Loading
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="size-6 animate-spin text-rt-fg-tertiary" />
        <span className="ml-2 text-rt-fg-tertiary text-sm">
          Loading @{username}...
        </span>
      </div>
    )
  }

  // Error
  if (isError || !data) {
    return (
      <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-10 text-center">
        <p className="text-rt-red text-sm">
          {error?.message || "Failed to load creator data"}
        </p>
        <Link
          to="/internal"
          className="text-rt-magenta text-sm mt-2 inline-block hover:underline"
        >
          Back to Internal TikTok
        </Link>
      </div>
    )
  }

  return (
    <div>
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-[13px] text-rt-fg-tertiary mb-2">
        <Link
          to="/internal"
          className="hover:text-rt-fg transition-colors"
        >
          Internal TikTok
        </Link>
        <ChevronRight className="size-3.5" />
        <span className="text-rt-fg font-medium">@{data.username}</span>
      </div>

      {/* Top bar */}
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h1 className="text-[22px] font-semibold">@{data.username}</h1>
          <p className="text-rt-fg-tertiary text-sm">
            Last 30 days &middot; {data.total_videos} posts
          </p>
        </div>
        <a
          href={`https://www.tiktok.com/@${data.username}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <Button variant="outline" size="sm">
            <ExternalLink className="size-3.5" />
            View on TikTok
          </Button>
        </a>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        {[
          { label: "Posts (30d)", value: data.total_videos.toString() },
          { label: "Total Views", value: data.total_views.toLocaleString() },
          { label: "Total Likes", value: data.total_likes.toLocaleString() },
          {
            label: "Unique Songs",
            value: (data.songs?.length ?? 0).toString(),
          },
        ].map((card) => (
          <div
            key={card.label}
            className="bg-rt-bg-card border border-white/8 rounded-[10px] p-4"
          >
            <div className="text-rt-fg-tertiary text-xs font-semibold uppercase tracking-wide mb-1">
              {card.label}
            </div>
            <div className="text-[22px] font-bold text-rt-fg">
              {card.value}
            </div>
          </div>
        ))}
      </div>

      {/* Songs list */}
      {data.songs && data.songs.length > 0 ? (
        <>
          <h3 className="text-[15px] font-semibold mb-3">
            Top Songs by Views
          </h3>
          {data.songs.map((song) => (
            <CreatorSongCard
              key={song.key || `${song.song}-${song.artist}`}
              song={song}
            />
          ))}
        </>
      ) : (
        <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-10 text-center">
          <p className="text-rt-fg-tertiary text-sm">
            No cached data for @{data.username} yet.
            <br />
            Run a scrape from the Internal TikTok page to populate.
          </p>
        </div>
      )}
    </div>
  )
}
