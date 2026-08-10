import { useState, useMemo } from "react"
import { Link } from "react-router-dom"
import type { InternalSongResult, InternalScrapeResults } from "@/lib/types"
import { ChevronDown, ChevronUp, Copy, Check } from "lucide-react"
import { Button } from "@/components/ui/button"

// ---- Song Card ----

function SongCard({ song }: { song: InternalSongResult }) {
  const [linksOpen, setLinksOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const linksText = song.videos.map((v) => v.url).join("\n")

  async function copyLinks() {
    await navigator.clipboard.writeText(linksText)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-4 mb-3">
      {/* Song header */}
      <div className="flex justify-between items-start">
        <div className="min-w-0 flex-1">
          <div className="text-[16px] font-semibold text-[#1a1a2e] truncate">
            {song.song}
          </div>
          <div className="text-[#888] text-[13px]">{song.artist}</div>
        </div>
        <div className="text-right flex-shrink-0 ml-4">
          <div className="text-[18px] font-bold text-[#1a1a2e]">
            {(song.total_views ?? 0).toLocaleString()}
          </div>
          <div className="text-[#888] text-[13px]">
            {song.videos.length} video{song.videos.length !== 1 ? "s" : ""}
          </div>
        </div>
      </div>

      {/* Accounts */}
      <div className="mt-2 text-[12px] text-[#888]">
        Accounts: {(song.accounts ?? []).join(", ") || "—"}
      </div>

      {/* Video table */}
      <div className="mt-2.5 overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-[#f0f0f5]">
              <th className="text-[11px] text-[#888] font-semibold uppercase tracking-wide px-2.5 py-1.5">
                Account
              </th>
              <th className="text-[11px] text-[#888] font-semibold uppercase tracking-wide px-2.5 py-1.5">
                Views
              </th>
              <th className="text-[11px] text-[#888] font-semibold uppercase tracking-wide px-2.5 py-1.5">
                Likes
              </th>
              <th className="text-[11px] text-[#888] font-semibold uppercase tracking-wide px-2.5 py-1.5">
                Link
              </th>
            </tr>
          </thead>
          <tbody>
            {song.videos.map((v, vi) => (
              <tr key={vi} className="border-b border-[#f0f0f5] last:border-b-0">
                <td className="px-2.5 py-1 text-[13px]">
                  <Link
                    to={`/internal/${v.account.replace(/^@/, "")}`}
                    className="text-[#0b62d6] hover:underline"
                  >
                    {v.account}
                  </Link>
                </td>
                <td className="px-2.5 py-1 text-[13px]">
                  {v.views.toLocaleString()}
                </td>
                <td className="px-2.5 py-1 text-[13px]">
                  {v.likes.toLocaleString()}
                </td>
                <td className="px-2.5 py-1 text-[13px]">
                  <a
                    href={v.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#0b62d6] hover:underline"
                  >
                    Open
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Expandable copy links */}
      <div className="mt-2.5">
        <button
          type="button"
          onClick={() => setLinksOpen(!linksOpen)}
          className="flex items-center gap-1 text-[13px] text-[#0b62d6] font-medium hover:underline"
        >
          Copy links ({song.videos.length})
          {linksOpen ? (
            <ChevronUp className="size-3.5" />
          ) : (
            <ChevronDown className="size-3.5" />
          )}
        </button>
        {linksOpen && (
          <div className="relative mt-1.5">
            <textarea
              readOnly
              value={linksText}
              className="w-full font-mono text-[12px] p-2 border border-[#ddd] rounded-md bg-[#f9f9fb] resize-y"
              style={{
                height: `${Math.max(60, song.videos.length * 22)}px`,
                maxHeight: "200px",
              }}
            />
            <Button
              type="button"
              variant="outline"
              size="xs"
              className="absolute top-1.5 right-1.5 text-[11px]"
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

// ---- Master Copy Section ----

function MasterCopySection({ songs }: { songs: InternalSongResult[] }) {
  const [copied, setCopied] = useState(false)

  const allLinksText = useMemo(() => {
    return songs
      .map((song) => {
        const header = `${song.song} - ${song.artist}\n${"=".repeat(60)}`
        const links = song.videos.map((v) => v.url).join("\n")
        return `${header}\n${links}`
      })
      .join("\n\n")
  }, [songs])

  async function copyAll() {
    await navigator.clipboard.writeText(allLinksText)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-4 mt-5">
      <div className="flex items-center justify-between mb-2.5">
        <h3 className="text-[15px] font-semibold">All Links (Copy/Paste)</h3>
        <Button
          type="button"
          size="sm"
          className="bg-[#0b62d6] hover:bg-[#0951b5] text-white text-xs"
          onClick={copyAll}
        >
          {copied ? (
            <>
              <Check className="size-3" /> Copied!
            </>
          ) : (
            <>
              <Copy className="size-3" /> Copy All
            </>
          )}
        </Button>
      </div>
      <textarea
        readOnly
        value={allLinksText}
        className="w-full h-[300px] font-mono text-[12px] p-2.5 border border-[#ddd] rounded-md bg-[#f9f9fb] resize-y"
      />
    </div>
  )
}

// ---- Main Export ----

interface SongsResultsProps {
  results: InternalScrapeResults | undefined
  isLoading: boolean
}

export function SongsResults({ results, isLoading }: SongsResultsProps) {
  if (isLoading) {
    return (
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-10 text-center">
        <p className="text-[#888] text-sm">Loading results...</p>
      </div>
    )
  }

  // Has results with songs
  if (results && results.songs && results.songs.length > 0) {
    return (
      <div>
        {/* Header */}
        <div className="flex items-baseline justify-between mb-3">
          <h3 className="text-[15px] font-semibold">
            Sounds Found ({results.songs.length})
            <span className="text-[#888] font-normal">
              {" "}
              &mdash; {results.hours}h window
            </span>
          </h3>
        </div>

        {/* Song cards */}
        {results.songs.map((song) => (
          <SongCard key={song.key || `${song.song}-${song.artist}`} song={song} />
        ))}

        {/* Master copy section */}
        <MasterCopySection songs={results.songs} />
      </div>
    )
  }

  // Has results but no songs
  if (results && results.scraped_at) {
    return (
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-10 text-center">
        <p className="text-[#888] text-sm">
          No videos found in the last {results.hours || 72} hours.
          <br />
          Try increasing the time window.
        </p>
      </div>
    )
  }

  // No results at all
  return (
    <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-10 text-center">
      <p className="text-[#888] text-sm">
        Click <strong>Run Scrape</strong> to scan internal creator accounts.
        <br />
        Results will appear here grouped by song.
      </p>
    </div>
  )
}
