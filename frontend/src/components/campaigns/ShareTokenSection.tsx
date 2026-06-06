import { useState } from "react"
import { useCreateShareToken, useShareTokens, useRevokeShareToken } from "@/lib/queries"
import type { ShareToken } from "@/lib/types"
import { Copy, Check, Link2, Trash2, Loader2, ExternalLink, Share2, Clock } from "lucide-react"

interface ShareTokenSectionProps {
  slug: string
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return ""
  try {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    })
  } catch {
    return dateStr
  }
}

function TokenRow({
  token,
  onRevoke,
  isRevoking,
}: {
  token: ShareToken
  onRevoke: (t: string) => void
  isRevoking: boolean
}) {
  const [copied, setCopied] = useState(false)
  const shareUrl = `${window.location.origin}/share/${token.token}`

  const handleCopy = () => {
    navigator.clipboard.writeText(shareUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const isExpired = token.expires_at ? new Date(token.expires_at) < new Date() : false
  const isActive = token.is_active && !isExpired

  return (
    <div
      className={`flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg border ${
        isActive
          ? "bg-rt-bg-card border-white/8"
          : "bg-[#f9f9fb] border-white/8 opacity-60"
      }`}
    >
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <Link2 className="size-3.5 text-rt-fg-tertiary shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {token.label && (
              <span className="text-[13px] font-medium text-rt-fg truncate">
                {token.label}
              </span>
            )}
            {!isActive && (
              <span className="text-[10px] font-semibold uppercase text-red-500 bg-red-50 px-1.5 py-0.5 rounded">
                {isExpired ? "expired" : "revoked"}
              </span>
            )}
          </div>
          <div className="text-[11px] text-[#aaa] truncate">{shareUrl}</div>
          <div className="flex items-center gap-3 text-[11px] text-[#aaa] mt-0.5">
            <span>Created {formatDate(token.created_at)}</span>
            {token.expires_at && (
              <span className="flex items-center gap-1">
                <Clock className="size-3" />
                Expires {formatDate(token.expires_at)}
              </span>
            )}
            {token.access_count > 0 && (
              <span>{token.access_count} views</span>
            )}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {isActive && (
          <>
            <a
              href={shareUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1.5 text-rt-fg-tertiary hover:text-[#6B21A8] hover:bg-[#6B21A8]/5 rounded-md transition-colors"
              title="Open dashboard"
            >
              <ExternalLink className="size-3.5" />
            </a>
            <button
              onClick={handleCopy}
              className="p-1.5 text-rt-fg-tertiary hover:text-[#6B21A8] hover:bg-[#6B21A8]/5 rounded-md transition-colors"
              title="Copy link"
            >
              {copied ? (
                <Check className="size-3.5 text-green-500" />
              ) : (
                <Copy className="size-3.5" />
              )}
            </button>
          </>
        )}
        {isActive && (
          <button
            onClick={() => onRevoke(token.token)}
            disabled={isRevoking}
            className="p-1.5 text-rt-fg-tertiary hover:text-red-500 hover:bg-red-50 rounded-md transition-colors disabled:opacity-50"
            title="Revoke token"
          >
            {isRevoking ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Trash2 className="size-3.5" />
            )}
          </button>
        )}
      </div>
    </div>
  )
}

export function ShareTokenSection({ slug }: ShareTokenSectionProps) {
  const [isCreating, setIsCreating] = useState(false)
  const [label, setLabel] = useState("")
  const [expiresDays, setExpiresDays] = useState<string>("")
  const [justCreatedUrl, setJustCreatedUrl] = useState<string | null>(null)
  const [justCopied, setJustCopied] = useState(false)

  const createToken = useCreateShareToken(slug)
  const { data: allTokens } = useShareTokens()
  const revokeToken = useRevokeShareToken()

  // Filter tokens for this campaign
  const campaignTokens = (allTokens || []).filter(
    (t) => t.campaign_slugs?.includes(slug)
  )
  const activeTokens = campaignTokens.filter(
    (t) => t.is_active && (!t.expires_at || new Date(t.expires_at) >= new Date())
  )

  const handleCreate = () => {
    createToken.mutate(
      {
        label: label || undefined,
        expires_days: expiresDays ? parseInt(expiresDays, 10) : undefined,
      },
      {
        onSuccess: (data) => {
          setJustCreatedUrl(data.url)
          navigator.clipboard.writeText(data.url)
          setJustCopied(true)
          setTimeout(() => setJustCopied(false), 3000)
          setLabel("")
          setExpiresDays("")
          setIsCreating(false)
        },
      }
    )
  }

  return (
    <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Share2 className="size-4 text-[#6B21A8]" />
          <h3 className="text-sm font-semibold text-rt-fg">
            Share with Client
          </h3>
          {activeTokens.length > 0 && (
            <span className="text-[11px] text-rt-fg-tertiary bg-[#f0f0f3] px-2 py-0.5 rounded-full">
              {activeTokens.length} active
            </span>
          )}
        </div>
        {!isCreating && (
          <button
            onClick={() => setIsCreating(true)}
            className="px-3 py-1.5 text-[12px] font-medium text-[#6B21A8] bg-[#6B21A8]/5 border border-[#6B21A8]/20 rounded-lg hover:bg-[#6B21A8]/10 transition-colors"
          >
            Generate Share Link
          </button>
        )}
      </div>

      {/* Just created feedback */}
      {justCreatedUrl && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-3 py-2 mb-3 flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="text-green-700 text-[13px] font-medium">
              {justCopied ? "Link copied to clipboard!" : "Share link created"}
            </p>
            <p className="text-green-600/70 text-[11px] truncate">{justCreatedUrl}</p>
          </div>
          <button
            onClick={() => {
              navigator.clipboard.writeText(justCreatedUrl)
              setJustCopied(true)
              setTimeout(() => setJustCopied(false), 2000)
            }}
            className="shrink-0 p-1.5 text-green-600 hover:bg-green-100 rounded-md transition-colors"
          >
            {justCopied ? <Check className="size-4" /> : <Copy className="size-4" />}
          </button>
        </div>
      )}

      {/* Create form */}
      {isCreating && (
        <div className="border border-white/8 rounded-lg p-3 mb-3 space-y-3">
          <div>
            <label className="text-[11px] font-semibold text-rt-fg-tertiary uppercase tracking-wider mb-1 block">
              Label (optional)
            </label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Q1 Report for Warner"
              className="w-full px-3 py-1.5 text-sm border border-white/8 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#6B21A8]/30 focus:border-[#6B21A8]/30"
            />
          </div>
          <div>
            <label className="text-[11px] font-semibold text-rt-fg-tertiary uppercase tracking-wider mb-1 block">
              Expires after (days, optional)
            </label>
            <input
              type="number"
              value={expiresDays}
              onChange={(e) => setExpiresDays(e.target.value)}
              placeholder="e.g. 30 (leave blank for no expiry)"
              min={1}
              className="w-full px-3 py-1.5 text-sm border border-white/8 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#6B21A8]/30 focus:border-[#6B21A8]/30"
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCreate}
              disabled={createToken.isPending}
              className="px-4 py-1.5 text-sm font-medium text-white bg-[#6B21A8] rounded-lg hover:bg-[#581c87] transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {createToken.isPending && <Loader2 className="size-3.5 animate-spin" />}
              Create Link
            </button>
            <button
              onClick={() => {
                setIsCreating(false)
                setLabel("")
                setExpiresDays("")
              }}
              className="px-4 py-1.5 text-sm font-medium text-rt-fg-tertiary hover:text-rt-fg transition-colors"
            >
              Cancel
            </button>
          </div>
          {createToken.isError && (
            <p className="text-red-500 text-[12px]">
              {createToken.error?.message || "Failed to create token"}
            </p>
          )}
        </div>
      )}

      {/* Existing tokens */}
      {campaignTokens.length > 0 && (
        <div className="space-y-2">
          {campaignTokens.map((token) => (
            <TokenRow
              key={token.token}
              token={token}
              onRevoke={(t) => revokeToken.mutate(t)}
              isRevoking={revokeToken.isPending}
            />
          ))}
        </div>
      )}

      {campaignTokens.length === 0 && !isCreating && (
        <p className="text-[#aaa] text-[13px]">
          No share links yet. Generate one to share analytics with your client.
        </p>
      )}
    </div>
  )
}
