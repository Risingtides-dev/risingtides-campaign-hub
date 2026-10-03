import { useParams, Link } from "react-router-dom"
import { useCampaignLinks, useCampaign } from "@/lib/queries"
import { ArrowLeft, Copy, ExternalLink } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useState } from "react"

function formatViews(value: number): string {
  if (!value) return "-"
  return value.toLocaleString("en-US")
}

export default function CampaignLinks() {
  const { slug } = useParams<{ slug: string }>()
  const { data: campaign } = useCampaign(slug!)
  const { data, isLoading, isError, error } = useCampaignLinks(slug!)
  const [copied, setCopied] = useState(false)

  const videos = data?.videos ?? []

  function copyAllLinks() {
    const urls = videos.map((v) => v.url).join("\n")
    navigator.clipboard.writeText(urls)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Link
          to={`/campaign/${slug}`}
          className="text-rt-fg-tertiary hover:text-rt-fg transition-colors"
        >
          <ArrowLeft className="size-5" />
        </Link>
        <div>
          <h1 className="text-[22px] font-semibold">
            {campaign?.title ?? slug} — Links
          </h1>
          <p className="text-rt-fg-tertiary text-sm">
            {videos.length} matched video{videos.length !== 1 ? "s" : ""}
          </p>
        </div>
        {videos.length > 0 && (
          <Button
            onClick={copyAllLinks}
            className="ml-auto bg-rt-magenta hover:bg-rt-purple text-white"
          >
            <Copy className="size-3.5" />
            {copied ? "Copied!" : "Copy All Links"}
          </Button>
        )}
      </div>

      {isLoading && (
        <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-10 text-center">
          <p className="text-rt-fg-tertiary text-sm">Loading links...</p>
        </div>
      )}

      {isError && (
        <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-10 text-center">
          <p className="text-rt-red text-sm">
            {error?.message || "Failed to load links"}
          </p>
        </div>
      )}

      {!isLoading && !isError && videos.length === 0 && (
        <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-10 text-center">
          <p className="text-rt-fg-tertiary text-sm">
            No matched videos yet. Run a scrape from the campaign page.
          </p>
        </div>
      )}

      {!isLoading && !isError && videos.length > 0 && (
        <div className="bg-rt-bg-card border border-white/8 rounded-[10px] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b-2 border-white/8">
                  <th className="text-left text-rt-fg-tertiary text-xs font-semibold uppercase tracking-[0.3px] px-4 py-3">
                    Creator
                  </th>
                  <th className="text-left text-rt-fg-tertiary text-xs font-semibold uppercase tracking-[0.3px] px-4 py-3">
                    Song
                  </th>
                  <th className="text-left text-rt-fg-tertiary text-xs font-semibold uppercase tracking-[0.3px] px-4 py-3">
                    Views
                  </th>
                  <th className="text-left text-rt-fg-tertiary text-xs font-semibold uppercase tracking-[0.3px] px-4 py-3">
                    Likes
                  </th>
                  <th className="text-left text-rt-fg-tertiary text-xs font-semibold uppercase tracking-[0.3px] px-4 py-3">
                    Date
                  </th>
                  <th className="text-left text-rt-fg-tertiary text-xs font-semibold uppercase tracking-[0.3px] px-4 py-3">
                    Link
                  </th>
                </tr>
              </thead>
              <tbody>
                {videos.map((v, i) => (
                  <tr
                    key={v.url || i}
                    className="border-b border-white/5 hover:bg-white/[0.03]"
                  >
                    <td className="px-4 py-2 text-[14px] font-medium">
                      {v.account ? `@${v.account.replace(/^@/, "")}` : "-"}
                    </td>
                    <td className="px-4 py-2 text-[14px]">
                      <div>{v.song || "-"}</div>
                      {v.artist && (
                        <div className="text-rt-fg-tertiary text-[13px]">
                          {v.artist}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2 text-[14px]">
                      {formatViews(v.views)}
                    </td>
                    <td className="px-4 py-2 text-[14px]">
                      {formatViews(v.likes)}
                    </td>
                    <td className="px-4 py-2 text-[14px] text-rt-fg-tertiary">
                      {v.upload_date || "-"}
                    </td>
                    <td className="px-4 py-2">
                      <a
                        href={v.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-rt-magenta hover:underline inline-flex items-center gap-1 text-[13px]"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <ExternalLink className="size-3" />
                        Open
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
