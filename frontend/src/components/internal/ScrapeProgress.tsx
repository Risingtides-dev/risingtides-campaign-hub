import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useInternalScrapeStatus, keys } from "@/lib/queries"
import { Loader2, CheckCircle, XCircle } from "lucide-react"
import type { ScrapeAccountLog } from "@/lib/types"

interface ScrapeProgressProps {
  /** Whether polling is enabled (turn on after triggering a scrape) */
  enabled: boolean
  /** Called when the scrape finishes, so the parent can reset state */
  onComplete: () => void
}

export function ScrapeProgress({ enabled, onComplete }: ScrapeProgressProps) {
  const queryClient = useQueryClient()
  const { data: status } = useInternalScrapeStatus(enabled)
  const completedRef = useRef(false)
  const [showSummary, setShowSummary] = useState(false)
  const [fadingOut, setFadingOut] = useState(false)

  useEffect(() => {
    // Reset the guard when a new scrape starts
    if (enabled && status?.running) {
      completedRef.current = false
      setShowSummary(false)
      setFadingOut(false)
    }
  }, [enabled, status?.running])

  useEffect(() => {
    if (status && status.done && !status.running && !completedRef.current) {
      completedRef.current = true
      setShowSummary(true)
      // Scrape finished -- refetch results + creators
      queryClient.invalidateQueries({ queryKey: keys.internalResults })
      queryClient.invalidateQueries({ queryKey: keys.internalCreators })

      // Fade out after 5 seconds
      const fadeTimer = setTimeout(() => setFadingOut(true), 5000)
      const hideTimer = setTimeout(() => {
        setShowSummary(false)
        onComplete()
      }, 5500)

      return () => {
        clearTimeout(fadeTimer)
        clearTimeout(hideTimer)
      }
    }
  }, [status, queryClient, onComplete])

  // Don't render anything if not active
  if (!enabled && !showSummary) return null
  if (!status) return null

  // Completion summary view
  if (showSummary && status.done) {
    const ok = status.accounts_completed - status.accounts_failed
    return (
      <div
        className={`mb-4 transition-opacity duration-500 ${fadingOut ? "opacity-0" : "opacity-100"}`}
      >
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] px-4 py-3 border-l-[3px] border-l-[#22c55e]">
          <div className="flex items-center gap-2.5">
            <CheckCircle className="size-4 text-[#22c55e] flex-shrink-0" />
            <span className="text-[13px] text-[#333]">
              Done: {ok}/{status.accounts_total} accounts, {status.videos_so_far} videos
              {status.accounts_failed > 0 && (
                <span className="text-[#ef4444]">, {status.accounts_failed} failed</span>
              )}
            </span>
          </div>
        </div>
      </div>
    )
  }

  // Not running yet
  if (!status.running) return null

  const pct = status.accounts_total > 0
    ? Math.round((status.accounts_completed / status.accounts_total) * 100)
    : 0

  // Reverse log so newest entries are on top
  const reversedLog = [...(status.log || [])].reverse()

  return (
    <div className="mb-4">
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] px-4 py-4 border-l-[3px] border-l-[#0b62d6]">
        {/* Progress bar */}
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[13px] font-medium text-[#1a1a2e]">Scraping accounts</span>
            <span className="text-[11px] text-[#888]">{pct}%</span>
          </div>
          <div className="w-full h-2 bg-[#f0f0f5] rounded-full overflow-hidden">
            <div
              className="h-full bg-[#0b62d6] rounded-full transition-all duration-500 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        {/* Stats row */}
        <div className="flex flex-wrap gap-x-4 gap-y-1 mb-3">
          <span className="text-[11px] text-[#888]">
            {status.accounts_completed}/{status.accounts_total} accounts
          </span>
          <span className="text-[11px] text-[#888]">
            {status.videos_so_far} videos found
          </span>
          {status.accounts_failed > 0 && (
            <span className="text-[11px] text-[#ef4444]">
              {status.accounts_failed} failed
            </span>
          )}
        </div>

        {/* Currently scraping */}
        {status.current_accounts.length > 0 && (
          <div className="mb-3">
            <div className="text-[11px] text-[#888] uppercase tracking-wide mb-1.5">
              Currently scraping
            </div>
            <div className="flex flex-wrap gap-1.5">
              {status.current_accounts.map((username) => (
                <div
                  key={username}
                  className="inline-flex items-center gap-1.5 bg-[#f0f4ff] text-[#0b62d6] text-[11px] px-2 py-0.5 rounded-full"
                >
                  <Loader2 className="size-3 animate-spin" />
                  @{username}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Completed log */}
        {reversedLog.length > 0 && (
          <div>
            <div className="text-[11px] text-[#888] uppercase tracking-wide mb-1.5">
              Completed
            </div>
            <div className="max-h-[200px] overflow-y-auto space-y-0.5">
              {reversedLog.map((entry: ScrapeAccountLog, i: number) => (
                <div
                  key={`${entry.username}-${i}`}
                  className="flex items-center gap-1.5 text-[12px] py-0.5"
                >
                  {entry.status === "ok" ? (
                    <>
                      <CheckCircle className="size-3.5 text-[#22c55e] flex-shrink-0" />
                      <span className="text-[#333]">
                        @{entry.username}
                        <span className="text-[#888]"> — {entry.video_count} videos</span>
                      </span>
                    </>
                  ) : (
                    <>
                      <XCircle className="size-3.5 text-[#ef4444] flex-shrink-0" />
                      <span className="text-[#ef4444]">
                        @{entry.username}
                        <span className="text-[#888]"> — failed</span>
                      </span>
                    </>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
