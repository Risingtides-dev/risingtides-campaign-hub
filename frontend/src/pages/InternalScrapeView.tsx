import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useParams, Link } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  useInternalCreators,
  useInternalGroups,
  useInternalResults,
  useStartInternalScrape,
  useInternalScrapeJobStatus,
  keys,
} from "@/lib/queries"
import { SongsResults } from "@/components/internal/SongsResults"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Loader2, ArrowLeft, RefreshCw, Play } from "lucide-react"
import type { InternalScrapeResults, JobScrapeStatus } from "@/lib/types"

/**
 * CATEGORIES drives the per-page config for /internal/scrape/:category.
 *
 * Each category maps to:
 *  - title: page heading
 *  - groupSlugs: which group rows feed the accounts list / count
 *  - scrapeGroup: the single group slug we pass to the RTA-16
 *    /api/internal/scrape/start endpoint
 *
 * The "internal" category aggregates several booker groups and therefore
 * has no single scrapeGroup. The RTA-16 endpoint only accepts one group
 * per call, so Run-now is disabled on that category until the backend
 * grows multi-group support.
 */
const CATEGORIES: Record<
  string,
  { title: string; groupSlugs: string[]; scrapeGroup?: string }
> = {
  internal: {
    title: "Internal Pages",
    groupSlugs: [
      "jake_balik",
      "john_smathers",
      "sam_hudgens",
      "eric_cromartie",
      "johnny_balik",
      "seeno",
    ],
    // No scrapeGroup -- aggregated category, see comment above.
  },
  warner: {
    title: "Warner Pages",
    groupSlugs: ["warner"],
    scrapeGroup: "warner",
  },
  atlantic: {
    title: "Atlantic Pages",
    groupSlugs: ["atlantic"],
    scrapeGroup: "atlantic",
  },
  warner_test: {
    title: "Warner Test Pages",
    groupSlugs: ["warner_test"],
    scrapeGroup: "warner_test",
  },
}

const DEFAULT_HOURS = 168 // 7 days -- matches RTA-16 backend default

export default function InternalScrapeView() {
  const { category } = useParams<{ category: string }>()
  const config = CATEGORIES[category || ""] || CATEGORIES.internal
  const canRunNow = !!config.scrapeGroup

  const [hours, setHours] = useState<number>(DEFAULT_HOURS)
  // jobId is the only piece of UI state we own; everything else is derived
  // from the mutation + per-job query. This keeps setState out of effects
  // (avoids react-hooks/set-state-in-effect cascading-render warnings).
  const [jobId, setJobId] = useState<string | null>(null)
  // Track which jobs we've already toasted/invalidated for, so the effect
  // doesn't double-fire across polling refetches.
  const handledJobIdsRef = useRef<Set<string>>(new Set())

  const queryClient = useQueryClient()
  const { data: groups } = useInternalGroups()
  const { data: creators } = useInternalCreators()
  const {
    data: results,
    isLoading: resultsLoading,
    refetch: refetchResults,
  } = useInternalResults()

  const startScrape = useStartInternalScrape()
  const { data: jobStatus } = useInternalScrapeJobStatus(jobId)

  // ---------------------------------------------------------------------------
  // Derived state -- single source of truth for the button label / disabled
  // ---------------------------------------------------------------------------

  const isStarting = startScrape.isPending
  const isRunning =
    !isStarting && jobId !== null && jobStatus?.state === "running"
  const isActive = isStarting || isRunning

  // ---------------------------------------------------------------------------
  // Trigger handler
  // ---------------------------------------------------------------------------

  const handleStart = useCallback(() => {
    if (!config.scrapeGroup) return
    startScrape.mutate(
      { group: config.scrapeGroup, hours },
      {
        onSuccess: (resp) => {
          setJobId(resp.job_id)
          if (resp.debounced) {
            // Soft toast -- attaching to an existing run, not an error.
            toast("Scrape already in progress", {
              description: "Attaching to the existing job for this group.",
            })
          } else {
            toast.success(`Scrape started for ${config.title.toLowerCase()}`)
          }
        },
        onError: (err: unknown) => {
          const message =
            err instanceof Error ? err.message : "Failed to start scrape"
          toast.error("Could not start scrape", { description: message })
        },
      }
    )
  }, [config.scrapeGroup, config.title, hours, startScrape])

  // ---------------------------------------------------------------------------
  // Terminal-state side effects (toast + invalidate + clear jobId)
  //
  // Guarded by handledJobIdsRef so a given jobId only fires once even if the
  // status query refetches after the terminal frame.
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!jobId || !jobStatus) return
    const terminal = jobStatus.state === "done" || jobStatus.state === "error"
    if (!terminal) return
    if (handledJobIdsRef.current.has(jobId)) return
    handledJobIdsRef.current.add(jobId)

    if (jobStatus.state === "done") {
      queryClient.invalidateQueries({ queryKey: keys.internalResults })
      queryClient.invalidateQueries({ queryKey: keys.internalCreators })
      const { n, m } = jobStatus.progress
      toast.success(`Scrape complete -- ${n} of ${m} accounts done`)
    } else {
      toast.error("Scrape failed", {
        description: jobStatus.error || "Unknown error",
      })
    }

    // Async cleanup of jobId so the button returns to idle without
    // synchronously setting state inside the effect body.
    const t = window.setTimeout(
      () => setJobId(null),
      jobStatus.state === "done" ? 1500 : 3000
    )
    return () => window.clearTimeout(t)
  }, [jobId, jobStatus, queryClient])

  // ---------------------------------------------------------------------------
  // Page derived data
  // ---------------------------------------------------------------------------

  const accountCount = useMemo(() => {
    if (!groups) return 0
    return groups
      .filter((g) => config.groupSlugs.includes(g.slug))
      .reduce((sum, g) => sum + g.member_count, 0)
  }, [groups, config.groupSlugs])

  // The results endpoint is global, not per-group. After a scoped scrape the
  // results naturally narrow to the scope; per-scope filtering on the read
  // side is a separate task.
  const filteredResults = useMemo((): InternalScrapeResults | undefined => {
    if (!results) return undefined
    return results
  }, [results])

  const buttonDisabled = !canRunNow || isActive
  const disabledReason = !canRunNow
    ? "Run-now not available for this category yet."
    : undefined

  return (
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <Link
            to="/internal"
            className="text-rt-magenta text-sm hover:underline flex items-center gap-1 mb-1"
          >
            <ArrowLeft className="size-3.5" /> Internal TikTok
          </Link>
          <h1 className="text-[22px] font-semibold">{config.title}</h1>
          <p className="text-rt-fg-tertiary text-sm">{accountCount} accounts</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-sm text-rt-fg">
            <span className="text-rt-fg-tertiary">Hours</span>
            <Input
              type="number"
              min={1}
              max={24 * 30}
              value={hours}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10)
                setHours(Number.isFinite(n) && n > 0 ? n : DEFAULT_HOURS)
              }}
              className="w-[90px] h-8 text-sm"
              disabled={isActive}
            />
          </label>
          {/* Wrap so the title shows on disabled state too -- a disabled
              <button> swallows pointer events. */}
          <span title={disabledReason}>
            <Button
              onClick={handleStart}
              className="bg-rt-magenta hover:bg-rt-purple text-white"
              disabled={buttonDisabled}
              aria-label={
                disabledReason
                  ? `Run scrape now (${disabledReason})`
                  : "Run scrape now"
              }
            >
              {isStarting ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Starting...
                </>
              ) : isRunning ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Scraping...
                </>
              ) : (
                <>
                  <Play className="size-4" /> Run scrape now
                </>
              )}
            </Button>
          </span>
        </div>
      </div>

      {/* Inline progress strip while a job is running */}
      {isActive && (
        <ScrapeJobProgressStrip status={jobStatus} starting={isStarting} />
      )}

      {/* Accounts list */}
      {creators && (
        <div className="bg-rt-bg-card border border-white/8 rounded-[10px] overflow-hidden mb-5">
          <div className="px-4 py-3 border-b border-white/8">
            <h3 className="text-[15px] font-semibold">
              Accounts ({accountCount})
            </h3>
          </div>
          <div className="px-4 py-2 flex flex-wrap gap-2">
            {creators
              .filter(() => {
                // Show all creators for "internal" category.
                // For warner/atlantic the scrape itself is already group-
                // scoped, so showing the broader list here is acceptable
                // until we surface per-group membership on the read side.
                return true
              })
              .sort((a, b) => (b.total_views ?? 0) - (a.total_views ?? 0))
              .slice(
                0,
                category === "internal"
                  ? undefined
                  : accountCount > 0
                    ? accountCount * 3
                    : 20
              )
              .map((c) => (
                <Link
                  key={c.username}
                  to={`/internal/${c.username}`}
                  className="text-rt-magenta text-[13px] hover:underline"
                >
                  @{c.username}
                </Link>
              ))}
          </div>
        </div>
      )}

      {/* Results header with refresh button */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[18px] font-semibold text-rt-fg">
          Scrape Results
          {results?.scraped_at && (
            <span className="text-[13px] text-rt-fg-tertiary font-normal ml-2">
              Last scraped:{" "}
              {new Date(results.scraped_at).toLocaleString("en-US", {
                month: "short",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
                hour12: true,
                timeZone: "America/New_York",
              })}{" "}
              EST
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

// ---------------------------------------------------------------------------
// Inline progress strip
// ---------------------------------------------------------------------------

interface ProgressStripProps {
  status: JobScrapeStatus | undefined
  starting: boolean
}

function ScrapeJobProgressStrip({ status, starting }: ProgressStripProps) {
  const n = status?.progress?.n ?? 0
  const m = status?.progress?.m ?? 0
  const pct = m > 0 ? Math.round((n / m) * 100) : 0
  const lastLog = status?.last_log?.trim()

  return (
    <div className="mb-4">
      <div className="bg-rt-bg-card border border-white/8 rounded-[10px] px-4 py-3 border-l-[3px] border-l-rt-magenta">
        <div className="flex items-center justify-between mb-1.5 gap-3">
          <span className="text-[13px] font-medium text-rt-fg">
            {starting ? "Starting scrape..." : `${n} of ${m} done`}
          </span>
          {!starting && (
            <span className="text-[11px] text-rt-fg-tertiary">{pct}%</span>
          )}
        </div>
        <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden">
          <div
            className="h-full bg-rt-magenta rounded-full transition-all duration-500 ease-out"
            style={{ width: starting ? "5%" : `${pct}%` }}
          />
        </div>
        {!starting && lastLog && (
          <div className="text-[11px] text-rt-fg-tertiary mt-2 truncate">
            {lastLog}
          </div>
        )}
      </div>
    </div>
  )
}
