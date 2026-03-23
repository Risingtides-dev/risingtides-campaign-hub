import { useState, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ExternalLink, Copy, Check, Loader2, AlertCircle, Link2 } from "lucide-react"
import type { CobrandStats, MatchedVideo } from "@/lib/types"

// --- Cobrand Stats Card ---

interface CobrandStatsCardProps {
  stats: CobrandStats | undefined
  isLoading: boolean
  isError: boolean
  error: Error | null
}

export function CobrandStatsCard({
  stats,
  isLoading,
  isError,
  error,
}: CobrandStatsCardProps) {
  if (isLoading) {
    return (
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-5">
        <h3 className="text-[15px] font-semibold mb-3">Cobrand Stats</h3>
        <div className="flex items-center gap-2 text-[#888] text-sm py-4">
          <Loader2 className="size-4 animate-spin" />
          Loading Cobrand data...
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-5">
        <h3 className="text-[15px] font-semibold mb-3">Cobrand Stats</h3>
        <div className="flex items-center gap-2 text-red-500 text-sm py-2">
          <AlertCircle className="size-4" />
          {error?.message || "Failed to load Cobrand stats"}
        </div>
      </div>
    )
  }

  if (!stats) return null

  const statItems = [
    { label: "Live Submissions", value: stats.live_submission_count },
    { label: "Draft Submissions", value: stats.draft_submission_count },
    { label: "Comments", value: stats.comment_count },
    { label: "Status", value: stats.status || "Unknown" },
  ]

  return (
    <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-5">
      <h3 className="text-[15px] font-semibold mb-3">Cobrand Stats</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {statItems.map((item) => (
          <div key={item.label}>
            <div className="text-[#888] text-xs font-semibold uppercase tracking-wide mb-1">
              {item.label}
            </div>
            <div className="text-[18px] font-bold text-[#1a1a2e]">
              {typeof item.value === "number"
                ? item.value.toLocaleString("en-US")
                : item.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// --- Cobrand Upload Section ---

interface CobrandUploadSectionProps {
  cobrandLink: string
  matchedVideos: MatchedVideo[]
  visible: boolean
}

// --- Cobrand Link Input (for connecting a tracking sheet) ---

interface CobrandLinkInputProps {
  currentShareUrl?: string
  onSave: (data: { share_url: string }) => void
  isPending: boolean
}

export function CobrandLinkInput({
  currentShareUrl,
  onSave,
  isPending,
}: CobrandLinkInputProps) {
  const [url, setUrl] = useState(currentShareUrl || "")
  const [saved, setSaved] = useState(false)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = url.trim()
    if (!trimmed) return
    onSave({ share_url: trimmed })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-5">
      <div className="flex items-center gap-2 mb-3">
        <Link2 className="size-4 text-[#0b62d6]" />
        <h3 className="text-[15px] font-semibold">
          {currentShareUrl ? "Cobrand Tracking Link" : "Connect Cobrand Tracking"}
        </h3>
      </div>
      {!currentShareUrl && (
        <p className="text-[13px] text-[#888] mb-3">
          Paste the Cobrand share URL to pull live performance data for this campaign.
        </p>
      )}
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://music.cobrand.com/promote/.../share/?token=..."
          className="flex-1 text-[13px]"
        />
        <Button
          type="submit"
          disabled={isPending || !url.trim()}
          className="bg-[#0b62d6] hover:bg-[#0951b5] text-white whitespace-nowrap"
        >
          {isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : saved ? (
            <Check className="size-3.5" />
          ) : null}
          {isPending ? "Saving..." : saved ? "Saved!" : currentShareUrl ? "Update" : "Connect"}
        </Button>
      </form>
    </div>
  )
}

// --- Cobrand Upload Section ---

export function CobrandUploadSection({
  cobrandLink,
  matchedVideos,
  visible,
}: CobrandUploadSectionProps) {
  const [copied, setCopied] = useState(false)
  const [iframeBlocked, setIframeBlocked] = useState(false)
  const iframeRef = useRef<HTMLIFrameElement>(null)

  useEffect(() => {
    if (!cobrandLink || !visible) return

    // Detect if iframe is blocked after 5s
    const timer = setTimeout(() => {
      try {
        const iframe = iframeRef.current
        if (!iframe) return
        const doc = iframe.contentDocument || iframe.contentWindow?.document
        if (!doc || !doc.body || doc.body.innerHTML === "") {
          setIframeBlocked(true)
        }
      } catch {
        setIframeBlocked(true)
      }
    }, 5000)

    return () => clearTimeout(timer)
  }, [cobrandLink, visible])

  if (!visible || !cobrandLink) return null

  const videoLinks = matchedVideos.map((v) => v.url).join("\n")

  function handleCopy() {
    navigator.clipboard.writeText(videoLinks).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[15px] font-semibold">Cobrand Upload</h3>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleCopy}>
            {copied ? (
              <Check className="size-3.5 text-green-600" />
            ) : (
              <Copy className="size-3.5" />
            )}
            {copied ? "Copied!" : "Copy All Links"}
          </Button>
          <Button
            asChild
            size="sm"
            className="bg-[#0b62d6] hover:bg-[#0951b5] text-white"
          >
            <a href={cobrandLink} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="size-3.5" />
              Open in New Tab
            </a>
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Iframe or fallback */}
        <div>
          {!iframeBlocked ? (
            <iframe
              ref={iframeRef}
              src={cobrandLink}
              className="w-full h-[500px] border border-[#ddd] rounded-lg bg-[#f9f9fb]"
              title="Cobrand Upload"
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-[500px] border border-dashed border-[#ddd] rounded-lg bg-[#f9f9fb] px-10 text-center">
              <p className="text-[#888] mb-3">
                Cobrand cannot be embedded in an iframe.
              </p>
              <Button
                asChild
                className="bg-[#0b62d6] hover:bg-[#0951b5] text-white"
              >
                <a href={cobrandLink} target="_blank" rel="noopener noreferrer">
                  Open Cobrand Upload Page
                </a>
              </Button>
            </div>
          )}
        </div>

        {/* Matched video links */}
        <div>
          <label className="block text-[13px] font-medium mb-1.5">
            Matched Video Links ({matchedVideos.length})
          </label>
          <textarea
            readOnly
            value={videoLinks}
            className="w-full h-[460px] font-mono text-[12px] border border-[#ddd] rounded-lg p-2.5 bg-[#f9f9fb] resize-y leading-[1.8]"
          />
        </div>
      </div>
    </div>
  )
}
