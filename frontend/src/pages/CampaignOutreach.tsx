import { useState, useMemo } from "react"
import { useParams, Link } from "react-router-dom"
import {
  Send,
  Trash2,
  ArrowLeft,
  Check,
  X,
  Clock,
  AlertCircle,
  Search,
  MessageCircle,
  UserPlus,
} from "lucide-react"
import {
  useOutreach,
  useAddToOutreach,
  useRemoveFromOutreach,
  useSendOutreach,
  useOutreachStatus,
  useConfirmOutreach,
  useCampaign,
} from "@/lib/queries"
import type { NetworkCreator, OutreachMessage } from "@/lib/types"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

const DEFAULT_TEMPLATE = `Hey {creator}! We have a new campaign for {artist} - "{song}". Your rate would be ${"{rate}"} for {posts} post(s).

Let me know if you're interested!`

function formatCurrency(value: number): string {
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

// Niche color palette
const NICHE_COLORS: Record<string, string> = {}
const COLOR_PALETTE = [
  "bg-blue-100 text-blue-700",
  "bg-purple-100 text-purple-700",
  "bg-green-100 text-green-700",
  "bg-amber-100 text-amber-700",
  "bg-rose-100 text-rose-700",
  "bg-cyan-100 text-cyan-700",
  "bg-indigo-100 text-indigo-700",
  "bg-orange-100 text-orange-700",
  "bg-teal-100 text-teal-700",
  "bg-pink-100 text-pink-700",
]
function getNicheColor(niche: string): string {
  if (!NICHE_COLORS[niche]) {
    NICHE_COLORS[niche] = COLOR_PALETTE[Object.keys(NICHE_COLORS).length % COLOR_PALETTE.length]
  }
  return NICHE_COLORS[niche]
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { color: string; label: string }> = {
    draft: { color: "bg-gray-100 text-gray-600", label: "Draft" },
    sent: { color: "bg-blue-100 text-blue-700", label: "Sent" },
    responded: { color: "bg-orange-100 text-orange-700", label: "Responded" },
    accepted: { color: "bg-green-100 text-green-700", label: "Accepted" },
    declined: { color: "bg-red-100 text-red-600", label: "Declined" },
    expired: { color: "bg-amber-100 text-amber-700", label: "Expired" },
    posted: { color: "bg-purple-100 text-purple-700", label: "Posted" },
    verified: { color: "bg-emerald-100 text-emerald-700", label: "Verified" },
  }
  const c = config[status] || { color: "bg-gray-100 text-gray-500", label: status }
  return <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${c.color}`}>{c.label}</span>
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "accepted": return <Check className="size-4 text-green-600" />
    case "responded": return <MessageCircle className="size-4 text-orange-500" />
    case "declined": return <X className="size-4 text-red-500" />
    case "sent": return <Clock className="size-4 text-blue-500" />
    case "expired": return <AlertCircle className="size-4 text-amber-500" />
    default: return null
  }
}

export default function CampaignOutreach() {
  const { slug = "" } = useParams()
  const { data: campaign } = useCampaign(slug)
  const { data: outreach, isLoading } = useOutreach(slug)
  const addToOutreach = useAddToOutreach(slug)
  const removeFromOutreach = useRemoveFromOutreach(slug)
  const sendOutreach = useSendOutreach(slug)
  const confirmOutreach = useConfirmOutreach(slug)

  const hasSent = outreach?.messages?.some((m) => m.status === "sent" || m.status === "responded") ?? false
  const { data: statusData } = useOutreachStatus(slug, hasSent)

  const [search, setSearch] = useState("")
  const [selectedCreators, setSelectedCreators] = useState<Set<string>>(new Set())
  const [rateOverrides, setRateOverrides] = useState<Record<string, string>>({})
  const [postsOverrides, setPostsOverrides] = useState<Record<string, string>>({})
  const [messageTemplate, setMessageTemplate] = useState("")
  const [referencePost, setReferencePost] = useState("")
  const [showSendConfirm, setShowSendConfirm] = useState(false)
  const [sendResult, setSendResult] = useState<{ sent: string[]; errors: Array<{ username: string; error: string }> } | null>(null)
  const [selectedNiche, setSelectedNiche] = useState<string | null>(null)

  const template = messageTemplate || outreach?.templates?.offer || DEFAULT_TEMPLATE
  const refPost = referencePost || (outreach?.campaign as Record<string, unknown>)?.reference_post as string || ""

  const networkCreators = outreach?.network_creators ?? []
  const messages = statusData?.messages ?? outreach?.messages ?? []
  const counts = statusData?.counts ?? { draft: 0, sent: 0, accepted: 0, declined: 0, expired: 0 }

  // Get message status map for creators already in outreach
  const outreachStatusMap = useMemo(() => {
    const map: Record<string, OutreachMessage> = {}
    messages.forEach((m) => { map[m.username] = m })
    return map
  }, [messages])

  // Collect all unique niches
  const allNiches = useMemo(() => {
    const set = new Set<string>()
    networkCreators.forEach((c) => (c.niches || []).forEach((n: string) => set.add(n)))
    return Array.from(set).sort()
  }, [networkCreators])

  // Filter creators by search + niche (show ALL creators, including those already in outreach)
  const filteredCreators = useMemo(() => {
    let list = networkCreators
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter((c) => c.username.toLowerCase().includes(q))
    }
    if (selectedNiche) {
      list = list.filter((c) => (c.niches || []).includes(selectedNiche))
    }
    return list
  }, [networkCreators, search, selectedNiche])

  // Only selectable creators (not already in outreach)
  const selectableCreators = useMemo(
    () => filteredCreators.filter((c) => !c.in_outreach),
    [filteredCreators]
  )

  const toggleCreator = (username: string) => {
    setSelectedCreators((prev) => {
      const next = new Set(prev)
      if (next.has(username)) next.delete(username)
      else next.add(username)
      return next
    })
  }

  const selectAllVisible = () => {
    if (selectedCreators.size === selectableCreators.length && selectableCreators.length > 0) {
      setSelectedCreators(new Set())
    } else {
      setSelectedCreators(new Set(selectableCreators.map((c) => c.username)))
    }
  }

  const handleAddAndSend = async () => {
    // First add selected creators to outreach as drafts
    const creators = Array.from(selectedCreators).map((username) => {
      const nc = networkCreators.find((c) => c.username === username)
      return {
        username,
        rate: parseFloat(rateOverrides[username] || "") || nc?.default_rate || 0,
        posts: parseInt(postsOverrides[username] || "") || nc?.default_posts || 1,
      }
    })

    if (creators.length > 0) {
      await addToOutreach.mutateAsync(creators)
    }

    setShowSendConfirm(true)
  }

  const handleSend = async () => {
    setShowSendConfirm(false)
    const result = await sendOutreach.mutateAsync({
      message_template: template,
      reference_post: refPost || undefined,
    })
    setSendResult(result)
    setSelectedCreators(new Set())
    setRateOverrides({})
    setPostsOverrides({})
    if (messageTemplate !== template) setMessageTemplate(template)
  }

  // Calculate total budget for selected
  const selectedBudget = useMemo(() => {
    return Array.from(selectedCreators).reduce((sum, username) => {
      const nc = networkCreators.find((c) => c.username === username)
      const rate = parseFloat(rateOverrides[username] || "") || nc?.default_rate || 0
      return sum + rate
    }, 0)
  }, [selectedCreators, rateOverrides, networkCreators])

  const draftCount = messages.filter((m) => m.status === "draft").length
  const totalToSend = selectedCreators.size + draftCount

  if (isLoading) {
    return (
      <div className="p-10 text-center">
        <p className="text-[#888] text-sm">Loading outreach...</p>
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link to="/network" className="text-[#888] hover:text-[#333] transition-colors">
          <ArrowLeft className="size-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-[22px] font-semibold">Build Campaign</h1>
          {campaign && (
            <p className="text-sm text-[#888]">
              {campaign.artist} — {campaign.song}
              {campaign.budget && (
                <span className="ml-2">
                  · {formatCurrency(campaign.budget.left)} remaining of {formatCurrency(campaign.budget.total)}
                </span>
              )}
            </p>
          )}
        </div>
        {/* Status summary pills */}
        <div className="hidden md:flex items-center gap-2">
          {[
            { label: "Sent", count: counts.sent, color: "bg-blue-50 text-blue-600" },
            { label: "Responded", count: counts.responded || 0, color: "bg-orange-50 text-orange-600" },
            { label: "Accepted", count: counts.accepted, color: "bg-green-50 text-green-600" },
            { label: "Declined", count: counts.declined, color: "bg-red-50 text-red-500" },
          ].filter((s) => s.count > 0).map((s) => (
            <span key={s.label} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${s.color}`}>
              {s.count} {s.label}
            </span>
          ))}
        </div>
      </div>

      {/* Creator Selection Table */}
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] mb-4">
        <div className="px-5 py-3.5 border-b border-[#e8e8ef]">
          <div className="flex items-center gap-3 flex-wrap">
            <h2 className="font-semibold text-[15px]">Select Creators</h2>
            <div className="relative flex-1 min-w-[180px] max-w-[260px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-[#888]" />
              <Input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search..."
                className="pl-9 h-8 text-sm"
              />
            </div>
            {/* Niche filter chips */}
            {allNiches.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap">
                {allNiches.map((niche) => (
                  <button
                    key={niche}
                    type="button"
                    onClick={() => setSelectedNiche(selectedNiche === niche ? null : niche)}
                    className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium transition-all ${
                      selectedNiche === niche
                        ? getNicheColor(niche) + " ring-2 ring-offset-1 ring-current"
                        : "bg-[#f0f0f5] text-[#666] hover:bg-[#e4e4ed]"
                    }`}
                  >
                    {niche}
                  </button>
                ))}
                {selectedNiche && (
                  <button
                    type="button"
                    onClick={() => setSelectedNiche(null)}
                    className="text-[11px] text-[#999] hover:text-[#555] underline"
                  >
                    clear
                  </button>
                )}
              </div>
            )}
            <div className="ml-auto flex items-center gap-2">
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={selectAllVisible}>
                {selectedCreators.size === selectableCreators.length && selectableCreators.length > 0
                  ? "Deselect All"
                  : "Select All"}
              </Button>
              <span className="text-[12px] text-[#888]">
                {filteredCreators.length} creator{filteredCreators.length !== 1 ? "s" : ""}
              </span>
            </div>
          </div>
        </div>

        <div className="max-h-[400px] overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-8 px-3" />
                <TableHead className="text-xs uppercase text-[#888]">Creator</TableHead>
                <TableHead className="text-xs uppercase text-[#888]">Niches</TableHead>
                <TableHead className="text-xs uppercase text-[#888]">Rate</TableHead>
                <TableHead className="text-xs uppercase text-[#888]">Posts</TableHead>
                <TableHead className="text-xs uppercase text-[#888]">ManyChat</TableHead>
                <TableHead className="text-xs uppercase text-[#888]">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredCreators.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-[#888] py-8 text-sm">
                    {networkCreators.length === 0
                      ? "No creators in network. Add creators on the Outreach Hub page first."
                      : "No creators match your filters."}
                  </TableCell>
                </TableRow>
              ) : (
                filteredCreators.map((nc) => {
                  const existingMsg = outreachStatusMap[nc.username]
                  const isInOutreach = !!nc.in_outreach
                  const isSelected = selectedCreators.has(nc.username)

                  return (
                    <TableRow
                      key={nc.username}
                      className={`transition-colors ${
                        isInOutreach
                          ? "bg-[#fafafa] opacity-70"
                          : isSelected
                            ? "bg-blue-50"
                            : "hover:bg-[#fafaff] cursor-pointer"
                      }`}
                      onClick={() => !isInOutreach && toggleCreator(nc.username)}
                    >
                      <TableCell className="px-3" onClick={(e) => e.stopPropagation()}>
                        {isInOutreach ? (
                          <Check className="size-4 text-green-400" />
                        ) : (
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleCreator(nc.username)}
                            className="rounded cursor-pointer"
                          />
                        )}
                      </TableCell>
                      <TableCell className="text-[14px] font-semibold">@{nc.username}</TableCell>
                      <TableCell>
                        {(nc.niches || []).length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {nc.niches.map((n: string) => (
                              <span key={n} className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium ${getNicheColor(n)}`}>
                                {n}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-[#ccc] text-xs">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {isInOutreach ? (
                          <span className="text-[13px]">{formatCurrency(existingMsg?.rate_offered ?? nc.default_rate)}</span>
                        ) : (
                          <Input
                            type="number"
                            className="w-20 h-7 text-xs"
                            value={rateOverrides[nc.username] ?? nc.default_rate}
                            onChange={(e) => {
                              e.stopPropagation()
                              setRateOverrides({ ...rateOverrides, [nc.username]: e.target.value })
                            }}
                            onClick={(e) => e.stopPropagation()}
                          />
                        )}
                      </TableCell>
                      <TableCell>
                        {isInOutreach ? (
                          <span className="text-[13px]">{existingMsg?.posts_offered ?? nc.default_posts}</span>
                        ) : (
                          <Input
                            type="number"
                            className="w-16 h-7 text-xs"
                            value={postsOverrides[nc.username] ?? nc.default_posts}
                            onChange={(e) => {
                              e.stopPropagation()
                              setPostsOverrides({ ...postsOverrides, [nc.username]: e.target.value })
                            }}
                            onClick={(e) => e.stopPropagation()}
                          />
                        )}
                      </TableCell>
                      <TableCell>
                        {nc.manychat_subscriber_id ? (
                          <Badge variant="outline" className="text-[10px] bg-green-50 text-green-700 border-green-200">
                            Linked
                          </Badge>
                        ) : (
                          <span className="text-[10px] text-red-400">Not linked</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {existingMsg ? (
                          <div className="flex items-center gap-1.5">
                            <StatusBadge status={existingMsg.status} />
                            {existingMsg.status === "draft" && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-red-400 hover:text-red-600 h-6 w-6 p-0"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  removeFromOutreach.mutate(nc.username)
                                }}
                              >
                                <Trash2 className="size-3" />
                              </Button>
                            )}
                          </div>
                        ) : (
                          <span className="text-[11px] text-[#ccc]">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Message Template */}
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] px-5 py-4 mb-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-[15px]">Message Template</h2>
          <div className="flex items-center gap-1.5">
            {["{creator}", "{artist}", "{song}", "{rate}", "{posts}"].map((tag) => (
              <button
                key={tag}
                type="button"
                className="px-2 py-0.5 text-[11px] bg-[#f0f0f5] hover:bg-[#e0e0e8] rounded text-[#555] transition-colors"
                onClick={() => {
                  const textarea = document.getElementById("msg-template") as HTMLTextAreaElement
                  if (textarea) {
                    const start = textarea.selectionStart
                    const end = textarea.selectionEnd
                    const current = messageTemplate || template
                    const newText = current.slice(0, start) + tag + current.slice(end)
                    setMessageTemplate(newText)
                  }
                }}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>
        <textarea
          id="msg-template"
          className="w-full border border-[#e8e8ef] rounded-lg px-3 py-2 text-[14px] min-h-[100px] resize-y focus:outline-none focus:ring-2 focus:ring-[#0b62d6]/20 focus:border-[#0b62d6]"
          value={messageTemplate || template}
          onChange={(e) => setMessageTemplate(e.target.value)}
          placeholder="Write your outreach message..."
        />
        {campaign && (
          <div className="mt-2 p-3 bg-[#f8f8fc] rounded-lg">
            <p className="text-xs text-[#888] mb-1 uppercase tracking-wide">Preview</p>
            <p className="text-[13px] text-[#333] whitespace-pre-wrap">
              {(messageTemplate || template)
                .replace("{creator}", Array.from(selectedCreators)[0] || messages[0]?.username || "creator_name")
                .replace("{artist}", campaign.artist || "Artist")
                .replace("{song}", campaign.song || "Song")
                .replace("{rate}", (() => {
                  const first = Array.from(selectedCreators)[0]
                  if (first) return rateOverrides[first] || networkCreators.find((c) => c.username === first)?.default_rate?.toString() || "100"
                  return messages[0]?.rate_offered?.toString() || "100"
                })())
                .replace("{posts}", (() => {
                  const first = Array.from(selectedCreators)[0]
                  if (first) return postsOverrides[first] || networkCreators.find((c) => c.username === first)?.default_posts?.toString() || "1"
                  return messages[0]?.posts_offered?.toString() || "1"
                })())}
            </p>
          </div>
        )}
      </div>

      {/* Reference Post / Sound Link */}
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] px-5 py-4 mb-4">
        <h2 className="font-semibold text-[15px] mb-2">Sound Link</h2>
        <p className="text-xs text-[#888] mb-2">TikTok sound or reference post URL — sent as a separate message after the offer so creators can copy-paste it.</p>
        <Input
          value={referencePost || (outreach?.campaign as Record<string, unknown>)?.reference_post as string || ""}
          onChange={(e) => setReferencePost(e.target.value)}
          placeholder="https://www.tiktok.com/music/..."
          className="text-[14px]"
        />
      </div>

      {/* Action bar */}
      {(selectedCreators.size > 0 || draftCount > 0) && (
        <div className="flex items-center justify-between bg-white border border-[#e8e8ef] rounded-[10px] px-5 py-4 mb-4">
          <div className="text-sm text-[#555]">
            {selectedCreators.size > 0 && (
              <span>
                <strong>{selectedCreators.size}</strong> selected · <strong>{formatCurrency(selectedBudget)}</strong> total
              </span>
            )}
            {selectedCreators.size > 0 && draftCount > 0 && <span className="mx-2 text-[#ccc]">+</span>}
            {draftCount > 0 && (
              <span><strong>{draftCount}</strong> draft{draftCount !== 1 ? "s" : ""} queued</span>
            )}
          </div>
          <Button
            onClick={handleAddAndSend}
            disabled={sendOutreach.isPending || addToOutreach.isPending}
            className="bg-[#0b62d6] hover:bg-[#0950b0]"
          >
            <Send className="size-4 mr-2" />
            Send Offers ({totalToSend})
          </Button>
        </div>
      )}

      {/* Send result */}
      {sendResult && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] px-5 py-4 mb-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-semibold text-sm">Send Results</h3>
            <Button variant="ghost" size="sm" onClick={() => setSendResult(null)}>
              <X className="size-3" />
            </Button>
          </div>
          {sendResult.sent.length > 0 && (
            <p className="text-sm text-green-600 mb-1">
              Sent to: {sendResult.sent.map((u) => `@${u}`).join(", ")}
            </p>
          )}
          {sendResult.errors.length > 0 && (
            <div className="text-sm text-red-600">
              {sendResult.errors.map((e) => (
                <p key={e.username}>@{e.username}: {e.error}</p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Outreach Status Table (shows after messages exist) */}
      {messages.length > 0 && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden">
          <div className="px-5 py-3.5 border-b border-[#e8e8ef] flex items-center justify-between">
            <h2 className="font-semibold text-[15px]">Outreach Status</h2>
            <div className="flex items-center gap-2">
              {[
                { label: "Draft", count: counts.draft, color: "text-gray-500" },
                { label: "Sent", count: counts.sent, color: "text-blue-600" },
                { label: "Accepted", count: counts.accepted, color: "text-green-600" },
                { label: "Declined", count: counts.declined, color: "text-red-500" },
              ].filter((s) => s.count > 0).map((s) => (
                <span key={s.label} className={`text-xs ${s.color}`}>
                  {s.count} {s.label}
                </span>
              ))}
            </div>
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="text-xs uppercase text-[#888]">Creator</TableHead>
                  <TableHead className="text-xs uppercase text-[#888]">Rate</TableHead>
                  <TableHead className="text-xs uppercase text-[#888]">Posts</TableHead>
                  <TableHead className="text-xs uppercase text-[#888]">Status</TableHead>
                  <TableHead className="text-xs uppercase text-[#888]">Reply</TableHead>
                  <TableHead className="text-xs uppercase text-[#888]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {messages.map((msg) => (
                  <TableRow
                    key={msg.id}
                    className={`hover:bg-[#fafaff] ${
                      msg.status === "responded" ? "bg-orange-50/50" :
                      msg.status === "declined" ? "bg-red-50/30" :
                      msg.status === "accepted" ? "bg-green-50/30" : ""
                    }`}
                  >
                    <TableCell className="text-[14px] font-semibold">
                      <div className="flex items-center gap-1.5">
                        <StatusIcon status={msg.status} />
                        @{msg.username}
                      </div>
                    </TableCell>
                    <TableCell className="text-[14px]">{formatCurrency(msg.rate_offered)}</TableCell>
                    <TableCell className="text-[14px]">{msg.posts_offered}</TableCell>
                    <TableCell><StatusBadge status={msg.status} /></TableCell>
                    <TableCell className="max-w-[200px]">
                      {msg.reply_text ? (
                        <div className={`text-[13px] rounded px-2 py-1 italic ${
                          msg.status === "accepted" ? "text-green-700 bg-green-50" :
                          msg.status === "declined" ? "text-red-600 bg-red-50" :
                          "text-[#333] bg-[#f8f8fc]"
                        }`}>
                          "{msg.reply_text}"
                        </div>
                      ) : (
                        <span className="text-[12px] text-[#ccc]">
                          {msg.sent_at ? "Awaiting reply..." : "—"}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        {msg.status === "responded" && (
                          <>
                            <Button
                              size="sm"
                              className="bg-green-600 hover:bg-green-700 text-white h-7 text-xs"
                              onClick={() => confirmOutreach.mutate(msg.username)}
                              disabled={confirmOutreach.isPending}
                            >
                              <UserPlus className="size-3 mr-1" />
                              Add to Campaign
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-red-500 hover:text-red-700 h-7 text-xs"
                              onClick={() => {/* TODO: decline endpoint */}}
                            >
                              <X className="size-3" />
                            </Button>
                          </>
                        )}
                        {msg.status === "draft" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-red-500 hover:text-red-700"
                            onClick={() => removeFromOutreach.mutate(msg.username)}
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        )}
                        {msg.status === "accepted" && (
                          <span className="text-xs text-green-600 font-medium flex items-center gap-1">
                            <Check className="size-3" /> Booked
                          </span>
                        )}
                        {msg.status === "declined" && (
                          <span className="text-xs text-red-500 font-medium">Passed</span>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {/* Send confirmation dialog */}
      <Dialog open={showSendConfirm} onOpenChange={setShowSendConfirm}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>Send Offers</DialogTitle>
          </DialogHeader>
          <div className="py-2">
            <p className="text-sm text-[#555] mb-4">
              Send outreach DMs to <strong>{totalToSend}</strong> creator{totalToSend !== 1 ? "s" : ""} via ManyChat?
            </p>
            <p className="text-xs text-[#888] mb-4">
              Each creator will receive a personalized TikTok DM with their rate and campaign details.
            </p>
            <div className="flex gap-2 justify-end">
              <Button variant="outline" onClick={() => setShowSendConfirm(false)}>Cancel</Button>
              <Button onClick={handleSend} disabled={sendOutreach.isPending} className="bg-[#0b62d6] hover:bg-[#0950b0]">
                <Send className="size-4 mr-1" /> Send DMs
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
