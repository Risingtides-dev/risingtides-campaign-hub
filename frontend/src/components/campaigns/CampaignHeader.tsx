import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Pencil, ExternalLink, BarChart3, RefreshCw, X, Plus, Loader2, Activity, FileText } from "lucide-react"
import type { CampaignDetail } from "@/lib/types"

interface CampaignHeaderProps {
  campaign: CampaignDetail
  onEdit: (data: Record<string, unknown>) => void | Promise<unknown>
  editError?: string
  onResetEdit?: () => void
  onRefresh: () => void
  isEditing: boolean
  isRefreshing: boolean
  onToggleCobrand?: () => void
  onCreateTracker?: () => void
  isCreatingTracker?: boolean
  onDropLink?: (url: string, expectedUrl: string) => Promise<unknown>
  isDroppingLink?: boolean
}

export function CampaignHeader({
  campaign,
  onEdit,
  editError,
  onResetEdit,
  onRefresh,
  isEditing: editPending,
  isRefreshing,
  onToggleCobrand,
  onCreateTracker,
  isCreatingTracker,
  onDropLink,
  isDroppingLink = false,
}: CampaignHeaderProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [droppedLink, setDroppedLink] = useState("")
  const [dropResult, setDropResult] = useState<{ ok: boolean; message: string } | null>(null)

  // Edit form state
  const [title, setTitle] = useState(campaign.title || "")
  const [soundId, setSoundId] = useState(campaign.official_sound || campaign.sound_id || "")
  const [ttArtistLabel, setTtArtistLabel] = useState(campaign.tt_artist_label || "")
  const [ttTrackName, setTtTrackName] = useState(campaign.tt_track_name || "")
  const [additionalSounds, setAdditionalSounds] = useState<string[]>(
    campaign.additional_sounds || []
  )
  const [startDate, setStartDate] = useState(campaign.start_date || "")
  const [endDate, setEndDate] = useState(campaign.end_date || "")
  const [budget, setBudget] = useState(campaign.budget?.total?.toString() || "0")
  const [cobrandLink, setCobrandLink] = useState(campaign.cobrand_link || "")
  const [editEndDateOriginal, setEditEndDateOriginal] = useState(campaign.end_date || "")
  const [editSoundOriginal, setEditSoundOriginal] = useState({
    value: campaign.official_sound || campaign.sound_id || "",
    revision: campaign.official_sound || "",
  })

  const soundCount =
    (campaign.sound_id || campaign.official_sound ? 1 : 0) +
    (campaign.additional_sounds?.length || 0)

  const budgetPct = campaign.budget?.pct ?? 0

  useEffect(() => {
    if (!isEditing) setSoundId(campaign.official_sound || campaign.sound_id || "")
  }, [campaign.official_sound, campaign.sound_id, isEditing])

  async function handleDropLink(e: React.FormEvent) {
    e.preventDefault()
    setDropResult(null)
    try {
      if (!onDropLink) return
      await onDropLink(droppedLink, campaign.official_sound || "")
      setDroppedLink("")
      setDropResult({ ok: true, message: "Link saved to this campaign." })
    } catch (error) {
      setDropResult({
        ok: false,
        message: error instanceof Error ? error.message : "Could not save that link. Try again.",
      })
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    const payload: Record<string, unknown> = {
      title,
      tt_artist_label: ttArtistLabel,
      tt_track_name: ttTrackName,
      additional_sounds: additionalSounds.filter((s) => s.trim()),
      start_date: startDate,
      budget: parseFloat(budget),
      cobrand_link: cobrandLink,
    }
    if (soundId !== editSoundOriginal.value || !/^https?:\/\//i.test(editSoundOriginal.value.trim())) {
      payload.sound_id = soundId
      if (/^https?:\/\//i.test(soundId.trim())) {
        payload.expected_official_sound = editSoundOriginal.revision
      }
    }
    if (endDate !== editEndDateOriginal) payload.end_date = endDate
    try {
      await onEdit(payload)
      setIsEditing(false)
    } catch { /* The parent exposes the mutation error and the form stays open. */ }
  }

  function openEdit() {
    onResetEdit?.()
    setTitle(campaign.title || "")
    setSoundId(campaign.official_sound || campaign.sound_id || "")
    setEditSoundOriginal({
      value: campaign.official_sound || campaign.sound_id || "",
      revision: campaign.official_sound || "",
    })
    setTtArtistLabel(campaign.tt_artist_label || "")
    setTtTrackName(campaign.tt_track_name || "")
    setAdditionalSounds(campaign.additional_sounds || [])
    setStartDate(campaign.start_date || "")
    setEndDate(campaign.end_date || "")
    setEditEndDateOriginal(campaign.end_date || "")
    setBudget(campaign.budget?.total?.toString() || "0")
    setCobrandLink(campaign.cobrand_link || "")
    setIsEditing(true)
  }

  function handleCancel() {
    onResetEdit?.()
    // Reset form state to current campaign values
    setTitle(campaign.title || "")
    setSoundId(campaign.official_sound || campaign.sound_id || "")
    setTtArtistLabel(campaign.tt_artist_label || "")
    setTtTrackName(campaign.tt_track_name || "")
    setAdditionalSounds(campaign.additional_sounds || [])
    setStartDate(campaign.start_date || "")
    setEndDate(campaign.end_date || "")
    setBudget(campaign.budget?.total?.toString() || "0")
    setCobrandLink(campaign.cobrand_link || "")
    setIsEditing(false)
  }

  function addSoundRow() {
    setAdditionalSounds([...additionalSounds, ""])
  }

  function removeSoundRow(index: number) {
    setAdditionalSounds(additionalSounds.filter((_, i) => i !== index))
  }

  function updateSound(index: number, value: string) {
    const updated = [...additionalSounds]
    updated[index] = value
    setAdditionalSounds(updated)
  }

  if (isEditing) {
    return (
      <div className="rounded-[10px] p-5 text-white" style={{ background: "#1a1a2e" }}>
        <form onSubmit={handleSave}>
          {editError && <div role="alert" className="mb-3 text-sm text-red-300">{editError}</div>}
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-full sm:w-auto">
              <label className="block text-xs opacity-60 mb-1">Title</label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full sm:w-[280px] bg-white/10 border-white/30 text-white placeholder:text-white/40"
              />
            </div>
            <div className="w-full sm:w-auto">
              <label className="block text-xs opacity-60 mb-1">Sound ID or URL</label>
              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <Input
                    value={soundId}
                    onChange={(e) => setSoundId(e.target.value)}
                    className="w-full sm:w-[240px] bg-white/10 border-white/30 text-white placeholder:text-white/40"
                  />
                  <button
                    type="button"
                    onClick={addSoundRow}
                    className="flex-shrink-0 flex items-center justify-center w-8 h-9 rounded-lg border border-white/30 bg-white/15 text-white hover:bg-white/25 transition-colors"
                  >
                    <Plus className="size-4" />
                  </button>
                </div>
                {additionalSounds.map((sound, i) => (
                  <div key={i} className="flex items-center gap-1.5">
                    <Input
                      value={sound}
                      onChange={(e) => updateSound(i, e.target.value)}
                      placeholder="Sound URL or ID"
                      className="w-full sm:w-[240px] bg-white/10 border-white/30 text-white placeholder:text-white/40"
                    />
                    <button
                      type="button"
                      onClick={() => removeSoundRow(i)}
                      className="flex-shrink-0 flex items-center justify-center w-8 h-9 rounded-lg border border-white/30 bg-red-500/30 text-white hover:bg-red-500/50 transition-colors"
                    >
                      <X className="size-4" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
            <div className="w-full sm:w-auto">
              <label className="block text-xs opacity-60 mb-1">TT Artist Label</label>
              <Input
                value={ttArtistLabel}
                onChange={(e) => setTtArtistLabel(e.target.value)}
                placeholder="e.g. Music for the Soul"
                className="w-full sm:w-[200px] bg-white/10 border-white/30 text-white placeholder:text-white/40"
              />
            </div>
            <div className="w-full sm:w-auto">
              <label className="block text-xs opacity-60 mb-1">TT Track Name</label>
              <Input
                value={ttTrackName}
                onChange={(e) => setTtTrackName(e.target.value)}
                placeholder="e.g. original sound"
                className="w-full sm:w-[200px] bg-white/10 border-white/30 text-white placeholder:text-white/40"
              />
            </div>
            <div className="w-full sm:w-auto">
              <label className="block text-xs opacity-60 mb-1">Start Date</label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full sm:w-[150px] bg-white/10 border-white/30 text-white"
              />
            </div>
            <div className="w-full sm:w-auto">
              <label className="block text-xs opacity-60 mb-1">End Date</label>
              <Input type="date" min={startDate} value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-full sm:w-[150px] bg-white/10 border-white/30 text-white" />
            </div>
            <div className="w-full sm:w-auto">
              <label className="block text-xs opacity-60 mb-1">Budget ($)</label>
              <Input
                type="number"
                step="0.01"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                className="w-full sm:w-[120px] bg-white/10 border-white/30 text-white"
              />
            </div>
            <div className="w-full sm:w-auto">
              <label className="block text-xs opacity-60 mb-1">Cobrand Upload Link</label>
              <Input
                value={cobrandLink}
                onChange={(e) => setCobrandLink(e.target.value)}
                placeholder="https://music.cobrand.com/promote/..."
                className="w-full sm:w-[340px] bg-white/10 border-white/30 text-white placeholder:text-white/40"
              />
            </div>
            <Button
              type="submit"
              disabled={editPending}
              className="bg-rt-magenta hover:bg-rt-purple text-white"
            >
              {editPending ? "Saving..." : "Save"}
            </Button>
            <Button
              type="button"
              disabled={editPending}
              onClick={handleCancel}
              className="bg-white/15 hover:bg-white/25 text-white border border-white/30"
            >
              Cancel
            </Button>
          </div>
        </form>
      </div>
    )
  }

  return (
    <div className="rounded-[10px] p-5 text-white" style={{ background: "#1a1a2e" }}>
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <h2 className="text-[20px] font-semibold mb-1">{campaign.title}</h2>
          <div className="text-[13px] opacity-70">
            {campaign.artist || ""}
            {campaign.start_date && (
              <> &middot; {campaign.start_date}</>
            )}
            {soundCount > 0 && (
              <>
                {" "}&middot; {soundCount} sound{soundCount > 1 ? "s" : ""}
              </>
            )}
            {campaign.tt_artist_label && (
              <>
                {" "}&middot; TT: {campaign.tt_artist_label}
                {campaign.tt_track_name && <> / {campaign.tt_track_name}</>}
              </>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {/* Budget info */}
          <div className="md:text-right">
            <div className="text-[13px] opacity-70">
              Budget: USD ${campaign.budget.total.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div className="w-40 bg-white/20 rounded-full h-2 mt-1">
              <div
                className="h-2 rounded-full transition-all duration-300 rt-gradient-bg"
                style={{ width: `${Math.min(budgetPct, 100)}%` }}
              />
            </div>
            <div className="text-[12px] opacity-60 mt-1">
              Booked: ${campaign.budget.booked.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              {" "}&middot;{" "}
              Paid: ${campaign.budget.paid.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              {" "}&middot;{" "}
              Left: ${campaign.budget.left.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>

          {/* Action buttons */}
          <Button
            onClick={openEdit}
            className="bg-white/15 hover:bg-white/25 text-white border border-white/30"
          >
            <Pencil className="size-3.5" />
            Edit
          </Button>

          <Button asChild className="bg-white/15 hover:bg-white/25 text-white border border-white/30">
            <Link to={`/campaign/${campaign.slug}/links`}>
              <ExternalLink className="size-3.5" />
              View Links
            </Link>
          </Button>

          <Button asChild className="bg-white/15 hover:bg-white/25 text-white border border-white/30">
            <Link to={`/campaign/${campaign.slug}/report`} target="_blank">
              <FileText className="size-3.5" />
              Client Report
            </Link>
          </Button>

          {campaign.cobrand_link && onToggleCobrand && (
            <Button
              onClick={onToggleCobrand}
              className="bg-white/15 hover:bg-white/25 text-white border border-white/30"
            >
              <BarChart3 className="size-3.5" />
              Cobrand
            </Button>
          )}

          {/* TidesTracker button */}
          {campaign.tracker_campaign_id ? (
            <Button
              asChild
              className="bg-purple-600/30 hover:bg-purple-600/50 text-purple-300 border border-purple-500/40"
            >
              <a
                href={campaign.tracker_url || "#"}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Activity className="size-3.5" />
                View Tracker
              </a>
            </Button>
          ) : campaign.cobrand_share_url && onCreateTracker ? (
            <Button
              onClick={onCreateTracker}
              disabled={isCreatingTracker}
              className="bg-purple-600/30 hover:bg-purple-600/50 text-purple-300 border border-purple-500/40"
            >
              {isCreatingTracker ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Activity className="size-3.5" />
              )}
              {isCreatingTracker ? "Creating..." : "Create Tracker"}
            </Button>
          ) : null}

          <Button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="bg-white/15 hover:bg-white/25 text-white border border-white/30"
          >
            {isRefreshing ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <RefreshCw className="size-3.5" />
            )}
            {isRefreshing ? "Refreshing..." : "Refresh Stats"}
          </Button>
        </div>
      </div>
      {onDropLink && <form onSubmit={handleDropLink} className="mt-4 border-t border-white/15 pt-4">
        <label htmlFor="campaign-sound-link" className="block text-xs font-medium mb-1.5">
          Drop a campaign link
        </label>
        <div className="flex flex-col sm:flex-row gap-2">
          <Input
            id="campaign-sound-link"
            type="url"
            value={droppedLink}
            onChange={(e) => {
              setDroppedLink(e.target.value)
              setDropResult(null)
            }}
            placeholder="Paste a unique https:// link"
            required
            className="flex-1 bg-white/10 border-white/30 text-white placeholder:text-white/40"
          />
          <Button
            type="submit"
            disabled={isDroppingLink}
            className="bg-rt-magenta hover:bg-rt-purple text-white"
          >
            {isDroppingLink ? <Loader2 className="size-3.5 animate-spin" /> : null}
            {isDroppingLink ? "Saving..." : "Save link"}
          </Button>
        </div>
        <p className="mt-1.5 text-xs opacity-60">
          Saves only this campaign’s official sound URL. Duplicate links are rejected.
        </p>
        {dropResult && (
          <p role="status" className={`mt-2 text-sm ${dropResult.ok ? "text-green-300" : "text-red-300"}`}>
            {dropResult.message}
          </p>
        )}
      </form>}
    </div>
  )
}
