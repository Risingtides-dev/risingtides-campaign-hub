import { useInbox, useCampaigns } from "@/lib/queries"
import { InboxCard } from "@/components/inbox/InboxCard"
import { Loader2 } from "lucide-react"

export default function SlackInbox() {
  const { data: items, isLoading, isError } = useInbox()
  const { data: campaigns } = useCampaigns()

  const pending = items?.filter((i) => i.status === "pending") ?? []
  const approved = items?.filter((i) => i.status === "approved") ?? []
  const dismissed = items?.filter((i) => i.status === "dismissed") ?? []

  const isEmpty = !pending.length && !approved.length && !dismissed.length

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-[22px] font-semibold">Slack Inbox</h1>
        <div className="text-[13px] text-rt-fg-tertiary">
          {isLoading ? "..." : `${pending.length} pending`}
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="size-6 animate-spin text-rt-fg-tertiary" />
        </div>
      )}

      {/* Error state */}
      {isError && (
        <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-6 text-center">
          <p className="text-[15px] text-rt-fg-tertiary">Failed to load inbox items.</p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !isError && isEmpty && (
        <div className="bg-rt-bg-card border border-white/8 rounded-[10px] py-[60px] px-5 text-center">
          <div className="text-[48px] opacity-30 mb-3">&#x1f4ec;</div>
          <div className="text-[15px] text-rt-fg-tertiary">No inbox items yet.</div>
          <div className="text-[13px] text-[#aaa] mt-2">
            When Open CLAW parses a booking from Slack, it'll appear here for your
            approval.
          </div>
          <div className="mt-5 text-[12px] text-[#bbb] bg-[#f7f7f9] p-4 rounded-lg text-left max-w-[500px] mx-auto">
            <div className="font-semibold mb-2 text-rt-fg-tertiary">API Endpoint</div>
            <code>POST /api/inbox</code>
            <pre className="mt-2 text-[11px] whitespace-pre-wrap">
{`{
  "source": "slack",
  "raw_message": "Book @xyzbca_quote for 5 posts at $150 on sombr",
  "campaign_name": "Sombr Homewrecker Promo R3",
  "campaign_slug": "sombr_homewrecker_promo_r3",
  "creators": [
    {"username": "xyzbca_quote", "posts_owed": 5, "total_rate": 150}
  ]
}`}
            </pre>
          </div>
        </div>
      )}

      {/* Pending section */}
      {pending.length > 0 && (
        <div className="mb-6">
          <div className="text-[13px] font-semibold text-rt-fg-tertiary uppercase tracking-wide mb-2">
            Pending Approval
          </div>
          {pending.map((item) => (
            <InboxCard key={item.id} item={item} campaigns={campaigns ?? []} />
          ))}
        </div>
      )}

      {/* Approved section */}
      {approved.length > 0 && (
        <div className="mb-6">
          <div className="text-[13px] font-semibold text-rt-fg-tertiary uppercase tracking-wide mb-2">
            Recently Approved
          </div>
          {approved.slice(0, 10).map((item) => (
            <InboxCard key={item.id} item={item} campaigns={campaigns ?? []} />
          ))}
        </div>
      )}

      {/* Dismissed section */}
      {dismissed.length > 0 && (
        <div>
          <div className="text-[13px] font-semibold text-rt-fg-tertiary uppercase tracking-wide mb-2">
            Dismissed
          </div>
          {dismissed.slice(0, 5).map((item) => (
            <InboxCard key={item.id} item={item} campaigns={campaigns ?? []} />
          ))}
        </div>
      )}
    </div>
  )
}
