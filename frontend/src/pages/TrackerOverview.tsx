import { Link } from "react-router-dom"
import { ArrowLeft, ExternalLink, Radar } from "lucide-react"

/* ============================================================
   TRACKER OVERVIEW — Mission Control
   Full-bleed iframe embed of the TidesTracker internal overview
   board. The embed key is injected at build time via
   VITE_TRACKER_EMBED_KEY (never committed to the repo).
   ============================================================ */

const TRACKER_BASE_URL =
  import.meta.env.VITE_TRACKER_BASE_URL || "https://risingtides-tracker.com"
const TRACKER_EMBED_KEY = import.meta.env.VITE_TRACKER_EMBED_KEY || ""

export default function TrackerOverview() {
  const embedUrl = `${TRACKER_BASE_URL}/internal?key=${TRACKER_EMBED_KEY}`

  return (
    // Counter Layout's main padding (p-6 md:px-8 md:py-6) so the board is full-bleed.
    <div className="-m-6 md:-mx-8 md:-my-6 flex h-dvh flex-col bg-[#060606]">
      {/* Minimal header bar */}
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-white/8 bg-rt-bg-raised px-4">
        <Link
          to="/trackers"
          className="inline-flex items-center gap-1.5 text-[13px] text-rt-fg-tertiary hover:text-rt-fg transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          Trackers
        </Link>
        <div className="h-4 w-px bg-white/10" />
        <div className="flex items-center gap-2 text-[13px] font-semibold text-rt-fg">
          <Radar className="size-4 text-purple-600" />
          Mission Control
        </div>
        <div className="flex-1" />
        <a
          href={embedUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-[13px] text-rt-fg-tertiary hover:text-purple-600 transition-colors"
        >
          Open in new tab
          <ExternalLink className="size-3.5" />
        </a>
      </div>

      {/* Board */}
      {TRACKER_EMBED_KEY ? (
        <iframe
          src={embedUrl}
          title="TidesTracker overview board"
          allow="fullscreen"
          loading="eager"
          className="h-full w-full flex-1 border-0 bg-[#060606]"
        />
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <div className="max-w-md rounded-xl border border-rt-red/30 bg-rt-red/10 px-5 py-4 text-center">
            <div className="text-[13px] font-medium text-rt-red">
              VITE_TRACKER_EMBED_KEY not set
            </div>
            <div className="mt-1 text-[12px] text-rt-fg-tertiary">
              Add it to the frontend build env to load the overview board.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
