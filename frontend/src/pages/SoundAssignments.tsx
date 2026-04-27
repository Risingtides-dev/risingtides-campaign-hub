import { useCallback, useEffect, useMemo, useState } from "react"
import { Search, RefreshCw, Send, Eye, AlertTriangle, X, Music, CheckCircle2, Loader2, EyeOff, Copy } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

// ---- Types (mirrors lab API responses) ----

interface Poster {
  poster_id: string
  name: string
  chat_id: number
  page_ids: string[]
  topics: Record<string, { topic_id: number; topic_name: string }>
  sounds_topic_id: number | null
  added_at: string
  updated_at: string
}

interface RosterPage {
  integration_id: string
  name: string
  provider: string
  picture: string | null
  project: string | null
}

interface Sound {
  id: string
  url: string
  label: string
  active: boolean
  added_at: string
}

interface TelegramStatus {
  bot_running: boolean
  sounds_bot_configured: boolean
  sounds_bot_running: boolean
  poster_count: number
  total_inventory: number
  schedule: { enabled?: boolean; last_run?: string | null }
}

interface SyncResult {
  active_campaigns: number
  completed_campaigns: number
  sounds_added: number
  sounds_deactivated: number
  sounds_reactivated: number
  matched_deterministic: number
  matched_ai: number
  unmatched: string[]
  errors: string[]
}

interface PreviewSection {
  integration_id: string
  page_name: string
  songs: { id: string; label: string; url: string }[]
}

interface PosterPreview {
  poster_id: string
  poster_name: string
  text: string
  page_count: number
  song_count: number
  sections: PreviewSection[]
  skipped_pages: { integration_id: string; page_name: string }[]
}

interface SendResult {
  ok: boolean
  sent: { poster_id: string; song_count: number; page_count: number }[]
  skipped: { poster_id: string; reason: string }[]
  errors: { poster_id: string; error: string }[]
  total_posters: number
}

// ---- Sound label helpers ----

// Labels look like "Artist - Song" or "Artist - Song r2" / "... R3" for later rounds.
// Round 1 is implicit (no suffix). We strip the suffix to get the song base.
function parseSoundLabel(label: string): { base: string; round: number } {
  const m = label.match(/^(.+?)\s+[Rr](\d+)\s*$/)
  if (m) return { base: m[1].trim(), round: parseInt(m[2], 10) }
  return { base: label.trim(), round: 1 }
}

// ---- API client ----

const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:5055" : "")

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api/sound-assignments${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || body.error || `Request failed (${res.status})`)
  }
  return res.json()
}

// ---- Page ----

export default function SoundAssignments() {
  const [posters, setPosters] = useState<Poster[]>([])
  const [pages, setPages] = useState<RosterPage[]>([])
  const [sounds, setSounds] = useState<Sound[]>([])
  const [playlists, setPlaylists] = useState<Record<string, string[]>>({})
  const [lastSync, setLastSync] = useState<SyncResult | null>(null)
  const [status, setStatus] = useState<TelegramStatus | null>(null)

  const [selectedPoster, setSelectedPoster] = useState<string | null>(null)
  const [selectedPage, setSelectedPage] = useState<string | null>(null)
  const [soundFilter, setSoundFilter] = useState("")
  const [pageFilter, setPageFilter] = useState("")
  const [showAllSounds, setShowAllSounds] = useState(false)

  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savingPage, setSavingPage] = useState<string | null>(null)

  const [previewPoster, setPreviewPoster] = useState<PosterPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [sendingPoster, setSendingPoster] = useState<string | null>(null)
  const [sendingAll, setSendingAll] = useState(false)
  const [bulkApplying, setBulkApplying] = useState(false)
  const [sendResult, setSendResult] = useState<SendResult | { single: true; poster_id: string; sent: boolean; reason?: string } | null>(null)

  // ---- Initial load ----

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [postersData, pagesData, soundsData, playlistsData, statusData] = await Promise.all([
        api<Poster[]>("/posters"),
        api<{ pages: RosterPage[] }>("/pages"),
        api<Sound[]>("/sounds?active_only=false"),
        api<Record<string, string[]>>("/playlists"),
        api<TelegramStatus>("/status").catch(() => null),
      ])
      setPosters(postersData)
      setPages(pagesData.pages || [])
      setSounds(soundsData)
      setPlaylists(playlistsData)
      setStatus(statusData)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load data")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  // ---- Lookups ----

  const pageById = useMemo(() => {
    const m: Record<string, RosterPage> = {}
    for (const p of pages) m[p.integration_id] = p
    return m
  }, [pages])

  const soundById = useMemo(() => {
    const m: Record<string, Sound> = {}
    for (const s of sounds) m[s.id] = s
    return m
  }, [sounds])

  const posterById = useMemo(() => {
    const m: Record<string, Poster> = {}
    for (const p of posters) m[p.poster_id] = p
    return m
  }, [posters])

  // Pages without a poster
  const unassignedPages = useMemo(() => {
    const owned = new Set<string>()
    for (const p of posters) for (const id of p.page_ids) owned.add(id)
    return pages.filter((pg) => !owned.has(pg.integration_id))
  }, [pages, posters])

  // ---- Selected poster's pages ----

  const selectedPosterObj = selectedPoster ? posterById[selectedPoster] : null
  const selectedPosterPages = useMemo(() => {
    if (!selectedPosterObj) return []
    return selectedPosterObj.page_ids
      .map((id) => pageById[id])
      .filter((p): p is RosterPage => Boolean(p))
  }, [selectedPosterObj, pageById])

  // Pages narrowed by the filter input.
  const visiblePosterPages = useMemo(() => {
    const q = pageFilter.trim().toLowerCase()
    if (!q) return selectedPosterPages
    return selectedPosterPages.filter((p) => p.name.toLowerCase().includes(q))
  }, [selectedPosterPages, pageFilter])

  const selectedPagePlaylist = selectedPage ? playlists[selectedPage] || [] : []
  const selectedPagePlaylistSet = useMemo(() => new Set(selectedPagePlaylist), [selectedPagePlaylist])

  // ---- Sound pool pipeline: sort → (hide inactive + collapse rounds) → search ----

  // 1. Sort by added_at desc (newest first). Stable order for everything below.
  const soundsByDate = useMemo(() => {
    return [...sounds].sort((a, b) => (b.added_at || "").localeCompare(a.added_at || ""))
  }, [sounds])

  // 2. Collapse: hide inactive, group rounds of the same song, keep one entry per
  //    song-base (preferring whichever round is currently assigned to the selected
  //    page so the user always sees what's actually in their playlist).
  const visibleSounds = useMemo(() => {
    if (showAllSounds) return soundsByDate

    const active = soundsByDate.filter((s) => s.active !== false)

    // For each song-base, decide which round to surface.
    const pickByBase = new Map<string, Sound>()
    const trackBase = (key: string, candidate: Sound, candidateRound: number) => {
      const existing = pickByBase.get(key)
      if (!existing) {
        pickByBase.set(key, candidate)
        return
      }
      const existingRound = parseSoundLabel(existing.label).round
      const existingAssigned = selectedPagePlaylistSet.has(existing.id)
      const candidateAssigned = selectedPagePlaylistSet.has(candidate.id)
      // Prefer the round currently assigned to the selected page; otherwise highest round.
      if (candidateAssigned && !existingAssigned) {
        pickByBase.set(key, candidate)
      } else if (!existingAssigned && candidateRound > existingRound) {
        pickByBase.set(key, candidate)
      }
    }
    for (const s of active) {
      const { base, round } = parseSoundLabel(s.label)
      trackBase(base.toLowerCase(), s, round)
    }

    const kept = new Set(pickByBase.values())
    return soundsByDate.filter((s) => kept.has(s))
  }, [soundsByDate, showAllSounds, selectedPagePlaylistSet])

  // 3. Apply text search.
  const filteredSounds = useMemo(() => {
    const q = soundFilter.trim().toLowerCase()
    if (!q) return visibleSounds
    return visibleSounds.filter((s) => s.label.toLowerCase().includes(q))
  }, [visibleSounds, soundFilter])

  // For the "show all" toggle copy: how many sounds are hidden right now.
  const hiddenSoundCount = sounds.length - visibleSounds.length

  // Map each base → all rounds (active or not), so a single visible row can show
  // "+2 older rounds" without re-deriving on every render.
  const roundsByBase = useMemo(() => {
    const m = new Map<string, Sound[]>()
    for (const s of sounds) {
      const base = parseSoundLabel(s.label).base.toLowerCase()
      const arr = m.get(base) || []
      arr.push(s)
      m.set(base, arr)
    }
    return m
  }, [sounds])

  // ---- Mutations ----

  async function toggleSound(pageId: string, soundId: string) {
    setSavingPage(pageId)
    try {
      const isAssigned = (playlists[pageId] || []).includes(soundId)
      const url = isAssigned
        ? `/pages/${pageId}/playlist/songs/${soundId}`
        : `/pages/${pageId}/playlist/songs`
      const result = await api<{ sound_ids: string[] }>(url, {
        method: isAssigned ? "DELETE" : "POST",
        body: isAssigned ? undefined : JSON.stringify({ sound_id: soundId }),
      })
      setPlaylists((prev) => ({ ...prev, [pageId]: result.sound_ids }))
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed")
    } finally {
      setSavingPage(null)
    }
  }

  // Copy the currently selected page's playlist to every OTHER page owned by the
  // same poster. One PUT per target page; runs in parallel; partial failure tolerated.
  async function applyPlaylistToAllPages() {
    if (!selectedPage || !selectedPosterObj) return
    const sourcePlaylist = playlists[selectedPage] || []
    const targetPages = selectedPosterObj.page_ids.filter((id) => id !== selectedPage)
    if (targetPages.length === 0) return
    const sourcePageName = pageById[selectedPage]?.name || "this page"
    const ok = confirm(
      `Apply ${sourcePlaylist.length} sounds from "${sourcePageName}" to ${targetPages.length} other page${targetPages.length > 1 ? "s" : ""}? This will replace each page's existing playlist.`,
    )
    if (!ok) return
    setBulkApplying(true)
    setError(null)
    try {
      const results = await Promise.allSettled(
        targetPages.map((pid) =>
          api<{ sound_ids: string[] }>(`/pages/${pid}/playlist`, {
            method: "PUT",
            body: JSON.stringify({ sound_ids: sourcePlaylist }),
          }).then((r) => ({ pid, sound_ids: r.sound_ids })),
        ),
      )
      const updates: Record<string, string[]> = {}
      const failed: string[] = []
      for (const r of results) {
        if (r.status === "fulfilled") {
          updates[r.value.pid] = r.value.sound_ids
        } else {
          failed.push(String(r.reason))
        }
      }
      if (Object.keys(updates).length > 0) {
        setPlaylists((prev) => ({ ...prev, ...updates }))
      }
      if (failed.length > 0) {
        setError(`Bulk apply: ${failed.length} page(s) failed — ${failed[0]}`)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bulk apply failed")
    } finally {
      setBulkApplying(false)
    }
  }

  async function syncSounds() {
    setSyncing(true)
    setError(null)
    try {
      const result = await api<SyncResult>("/sync", { method: "POST" })
      setLastSync(result)
      // Reload sound pool after sync
      const soundsData = await api<Sound[]>("/sounds?active_only=false")
      setSounds(soundsData)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed")
    } finally {
      setSyncing(false)
    }
  }

  async function openPreview(posterId: string) {
    setPreviewLoading(true)
    setError(null)
    try {
      const preview = await api<PosterPreview>(`/posters/${posterId}/preview`)
      setPreviewPoster(preview)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview failed")
    } finally {
      setPreviewLoading(false)
    }
  }

  async function sendToPoster(posterId: string) {
    setSendingPoster(posterId)
    setError(null)
    setSendResult(null)
    try {
      const result = await api<{ ok: boolean; sent: boolean; reason?: string; poster_id: string }>(
        `/send/${posterId}`,
        { method: "POST" },
      )
      setSendResult({ single: true, ...result })
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send failed")
    } finally {
      setSendingPoster(null)
    }
  }

  async function sendToAll() {
    if (!confirm("Send personalized sound assignments to ALL posters? This will dispatch Telegram messages.")) {
      return
    }
    setSendingAll(true)
    setError(null)
    setSendResult(null)
    try {
      const result = await api<SendResult>("/send-all", { method: "POST" })
      setSendResult(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send-all failed")
    } finally {
      setSendingAll(false)
    }
  }

  // ---- Render ----

  if (loading) {
    return (
      <div className="p-8">
        <Loader2 className="w-6 h-6 animate-spin text-[#0b62d6]" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#1a1a2e]">Sound Assignments</h1>
          <p className="text-sm text-[#666] mt-1">
            Assign sounds to each page. Posters receive a daily message grouped by their pages.
          </p>
          {status && (
            <div className="mt-2">
              {status.sounds_bot_running ? (
                <Badge className="bg-green-100 text-green-800 border-green-200">
                  <CheckCircle2 className="w-3 h-3 mr-1" /> Sounds bot online
                </Badge>
              ) : (
                <Badge className="bg-red-100 text-red-800 border-red-200">
                  <AlertTriangle className="w-3 h-3 mr-1" />
                  {status.sounds_bot_configured ? "Sounds bot offline" : "Sounds bot not configured"}
                </Badge>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={syncSounds} disabled={syncing}>
            {syncing ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <RefreshCw className="w-4 h-4 mr-2" />}
            Sync Sounds
          </Button>
          <Button
            onClick={sendToAll}
            disabled={sendingAll || !status?.sounds_bot_running}
            title={!status?.sounds_bot_running ? "Sounds bot must be running to send" : ""}
          >
            {sendingAll ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Send className="w-4 h-4 mr-2" />}
            Send to All Posters
          </Button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 rounded-md p-3 flex items-start justify-between">
          <div className="flex gap-2 items-start">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
            <span className="text-sm">{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-red-600 hover:text-red-800">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Sync stats + unmatched warning */}
      {lastSync && (
        <Card className={lastSync.unmatched.length > 0 ? "border-amber-300 bg-amber-50" : ""}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              {lastSync.unmatched.length > 0 ? (
                <AlertTriangle className="w-4 h-4 text-amber-600" />
              ) : (
                <CheckCircle2 className="w-4 h-4 text-green-600" />
              )}
              Last Sync
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            <div className="flex flex-wrap gap-4 text-[#555]">
              <span>{lastSync.active_campaigns} active campaigns</span>
              <span>+{lastSync.sounds_added} added</span>
              <span>{lastSync.matched_deterministic} matched directly</span>
              <span>{lastSync.matched_ai} matched via AI</span>
              {lastSync.sounds_deactivated > 0 && (
                <span>{lastSync.sounds_deactivated} deactivated</span>
              )}
            </div>
            {lastSync.unmatched.length > 0 && (
              <div className="pt-2 border-t border-amber-200">
                <div className="font-semibold text-amber-900 mb-1">
                  {lastSync.unmatched.length} active campaigns have no Notion sound link:
                </div>
                <ul className="list-disc list-inside text-amber-800 space-y-0.5">
                  {lastSync.unmatched.map((u) => (
                    <li key={u}>{u}</li>
                  ))}
                </ul>
                <div className="text-xs text-amber-700 mt-2">
                  Fix these in Notion (add the TikTok Sound Link), then click Sync Sounds again.
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Three-column layout */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 min-h-[600px]">
        {/* Posters column */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Posters ({posters.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {posters.map((p) => {
              const totalSongs = p.page_ids.reduce(
                (sum, pid) => sum + (playlists[pid] || []).length,
                0,
              )
              return (
                <button
                  key={p.poster_id}
                  onClick={() => {
                    setSelectedPoster(p.poster_id)
                    setSelectedPage(null)
                  }}
                  className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex justify-between items-center ${
                    selectedPoster === p.poster_id
                      ? "bg-[#eef2ff] text-[#0b62d6] font-semibold"
                      : "hover:bg-[#f0f0f5] text-[#333]"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    {p.name}
                    {!p.sounds_topic_id && (
                      <span title="No Sounds topic yet — will auto-create on first send">
                        <AlertTriangle className="w-3 h-3 text-amber-500" />
                      </span>
                    )}
                  </span>
                  <Badge variant="secondary" className="text-xs">
                    {p.page_ids.length}p · {totalSongs}s
                  </Badge>
                </button>
              )
            })}

            {unassignedPages.length > 0 && (
              <>
                <div className="pt-3 mt-3 border-t border-[#e8e8ef] text-[11px] uppercase font-semibold text-[#999] tracking-wide">
                  Unassigned ({unassignedPages.length})
                </div>
                <div className="text-xs text-[#888] px-3 py-1.5 italic">
                  Pages without a poster — assign in content lab.
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Pages column */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">
              {selectedPosterObj ? `${selectedPosterObj.name}'s Pages` : "Pages"}
              {selectedPosterObj && (
                <span className="text-[#888] font-normal ml-1">({selectedPosterPages.length})</span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {!selectedPoster && (
              <div className="text-sm text-[#888] italic px-3 py-6 text-center">
                Select a poster to see their pages
              </div>
            )}
            {selectedPoster && selectedPosterPages.length === 0 && (
              <div className="text-sm text-[#888] italic px-3 py-6 text-center">
                This poster has no pages assigned
              </div>
            )}
            {selectedPoster && selectedPosterPages.length > 0 && (
              <div className="relative pb-2">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#888]" />
                <Input
                  placeholder="Filter pages..."
                  value={pageFilter}
                  onChange={(e) => setPageFilter(e.target.value)}
                  className="pl-9 h-8 text-sm"
                />
              </div>
            )}
            {selectedPoster && selectedPosterPages.length > 0 && visiblePosterPages.length === 0 && (
              <div className="text-xs text-[#888] italic px-3 py-3 text-center">
                No pages match "{pageFilter}"
              </div>
            )}
            {visiblePosterPages.map((page) => {
              const playlist = playlists[page.integration_id] || []
              const activeCount = playlist.filter((sid) => soundById[sid]?.active !== false).length
              const isEmpty = playlist.length === 0
              // Preview: first 2 active song-base names, comma-separated.
              const previewSongs = playlist
                .map((sid) => soundById[sid])
                .filter((s): s is Sound => Boolean(s) && s.active !== false)
                .slice(0, 2)
                .map((s) => parseSoundLabel(s.label).base)
              const overflow = activeCount - previewSongs.length
              const isSelected = selectedPage === page.integration_id
              return (
                <button
                  key={page.integration_id}
                  onClick={() => setSelectedPage(page.integration_id)}
                  className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                    isSelected
                      ? "bg-[#eef2ff] text-[#0b62d6] font-semibold"
                      : "hover:bg-[#f0f0f5] text-[#333]"
                  }`}
                >
                  <div className="flex justify-between items-center gap-2">
                    <span className="truncate">{page.name}</span>
                    <Badge
                      variant={isEmpty ? "outline" : "secondary"}
                      className={`text-xs shrink-0 ${isEmpty ? "border-amber-300 text-amber-700" : ""}`}
                    >
                      {activeCount}{playlist.length !== activeCount && `/${playlist.length}`}
                    </Badge>
                  </div>
                  {previewSongs.length > 0 && (
                    <div
                      className={`text-[11px] mt-0.5 truncate ${isSelected ? "text-[#5a7fbf]" : "text-[#888]"}`}
                    >
                      {previewSongs.join(", ")}
                      {overflow > 0 && ` +${overflow} more`}
                    </div>
                  )}
                </button>
              )
            })}

            {/* Poster-level actions */}
            {selectedPosterObj && (
              <div className="pt-4 mt-4 border-t border-[#e8e8ef] flex flex-col gap-2">
                {selectedPage && selectedPosterPages.length > 1 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={applyPlaylistToAllPages}
                    disabled={bulkApplying}
                    title={`Replace every other page's playlist with the one on "${pageById[selectedPage]?.name || selectedPage}"`}
                  >
                    {bulkApplying ? (
                      <Loader2 className="w-4 h-4 animate-spin mr-2" />
                    ) : (
                      <Copy className="w-4 h-4 mr-2" />
                    )}
                    Apply to all {selectedPosterPages.length} pages
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => openPreview(selectedPosterObj.poster_id)}
                  disabled={previewLoading}
                >
                  {previewLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  ) : (
                    <Eye className="w-4 h-4 mr-2" />
                  )}
                  Preview Send
                </Button>
                <Button
                  size="sm"
                  onClick={() => sendToPoster(selectedPosterObj.poster_id)}
                  disabled={sendingPoster === selectedPosterObj.poster_id || !status?.sounds_bot_running}
                  title={!status?.sounds_bot_running ? "Sounds bot must be running to send" : ""}
                >
                  {sendingPoster === selectedPosterObj.poster_id ? (
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  ) : (
                    <Send className="w-4 h-4 mr-2" />
                  )}
                  Send to {selectedPosterObj.name}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Sound pool / playlist column */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Music className="w-4 h-4" />
              {selectedPage
                ? `Playlist for "${pageById[selectedPage]?.name || selectedPage}"`
                : `Sound Pool (${sounds.length})`}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#888]" />
              <Input
                placeholder="Filter sounds..."
                value={soundFilter}
                onChange={(e) => setSoundFilter(e.target.value)}
                className="pl-9"
              />
            </div>

            {/* Show-all toggle — surfaces inactive sounds and older rounds */}
            <div className="flex items-center justify-between text-xs text-[#666] px-1">
              <button
                onClick={() => setShowAllSounds((v) => !v)}
                className="flex items-center gap-1.5 hover:text-[#0b62d6] transition-colors"
                title={
                  showAllSounds
                    ? "Hide inactive sounds and older rounds"
                    : "Show every sound including inactive and older rounds"
                }
              >
                {showAllSounds ? (
                  <EyeOff className="w-3.5 h-3.5" />
                ) : (
                  <Eye className="w-3.5 h-3.5" />
                )}
                <span>{showAllSounds ? "Hide older / inactive" : "Show all rounds"}</span>
              </button>
              {!showAllSounds && hiddenSoundCount > 0 && (
                <span className="text-[#999]">{hiddenSoundCount} hidden</span>
              )}
            </div>

            {!selectedPage && (
              <div className="text-sm text-[#888] italic px-3 py-3 text-center">
                Select a page to assign sounds
              </div>
            )}

            <div className="max-h-[480px] overflow-y-auto space-y-1">
              {filteredSounds.map((sound) => {
                const isAssigned = selectedPagePlaylistSet.has(sound.id)
                const isInactive = !sound.active
                const disabled = !selectedPage || savingPage === selectedPage
                const { base, round } = parseSoundLabel(sound.label)
                const allRounds = roundsByBase.get(base.toLowerCase()) || []
                const olderCount = !showAllSounds
                  ? allRounds.filter((r) => r.id !== sound.id && r.active !== false).length
                  : 0
                return (
                  <button
                    key={sound.id}
                    onClick={() => selectedPage && toggleSound(selectedPage, sound.id)}
                    disabled={disabled}
                    className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center gap-2 ${
                      isAssigned
                        ? "bg-green-50 text-green-900 border border-green-200"
                        : selectedPage
                          ? "hover:bg-[#f0f0f5] text-[#333] border border-transparent"
                          : "text-[#888] cursor-not-allowed border border-transparent"
                    } ${isInactive ? "opacity-60" : ""}`}
                  >
                    <div className="w-4 h-4 shrink-0 flex items-center justify-center">
                      {isAssigned ? (
                        <CheckCircle2 className="w-4 h-4 text-green-600" />
                      ) : (
                        <div className="w-3.5 h-3.5 rounded border border-[#ccc]" />
                      )}
                    </div>
                    <span className={`truncate ${isInactive ? "line-through" : ""}`}>
                      {base}
                    </span>
                    {round > 1 && (
                      <Badge variant="outline" className="text-[10px] shrink-0 px-1.5 py-0 h-4">
                        R{round}
                      </Badge>
                    )}
                    {olderCount > 0 && (
                      <Badge
                        variant="outline"
                        className="text-[10px] shrink-0 px-1.5 py-0 h-4 text-[#888] border-[#ddd]"
                        title={`${olderCount} older round${olderCount > 1 ? "s" : ""} hidden — click "Show all rounds" to reveal`}
                      >
                        +{olderCount}
                      </Badge>
                    )}
                    {isInactive && (
                      <Badge variant="outline" className="ml-auto text-xs shrink-0">
                        inactive
                      </Badge>
                    )}
                  </button>
                )
              })}
              {filteredSounds.length === 0 && (
                <div className="text-sm text-[#888] italic px-3 py-3 text-center">
                  {soundFilter ? "No sounds match filter" : "No sounds in pool — click Sync Sounds"}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Send result */}
      {sendResult && (
        <Card className={
          ("errors" in sendResult && sendResult.errors.length > 0)
            ? "border-amber-300"
            : "border-green-300"
        }>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-green-600" />
              Send Result
              <button onClick={() => setSendResult(null)} className="ml-auto text-[#888] hover:text-[#333]">
                <X className="w-4 h-4" />
              </button>
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            {"single" in sendResult && sendResult.single ? (
              <div>
                {sendResult.sent ? (
                  <div className="flex items-center gap-2 text-green-700">
                    <CheckCircle2 className="w-4 h-4" /> Sent to {sendResult.poster_id}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-amber-700">
                    <AlertTriangle className="w-4 h-4" /> Skipped {sendResult.poster_id}: {sendResult.reason}
                  </div>
                )}
              </div>
            ) : (
              <>
                <div className="flex flex-wrap gap-3 text-[#555]">
                  <span className="text-green-700">
                    {(sendResult as SendResult).sent.length} sent
                  </span>
                  {(sendResult as SendResult).skipped.length > 0 && (
                    <span className="text-amber-700">
                      {(sendResult as SendResult).skipped.length} skipped
                    </span>
                  )}
                  {(sendResult as SendResult).errors.length > 0 && (
                    <span className="text-red-700">
                      {(sendResult as SendResult).errors.length} errors
                    </span>
                  )}
                </div>
                {(sendResult as SendResult).sent.length > 0 && (
                  <div>
                    <div className="font-medium text-[#333] mt-2">Sent:</div>
                    <ul className="text-xs text-[#666] space-y-0.5">
                      {(sendResult as SendResult).sent.map((r) => (
                        <li key={r.poster_id}>
                          {r.poster_id} — {r.song_count} songs across {r.page_count} pages
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {(sendResult as SendResult).skipped.length > 0 && (
                  <div>
                    <div className="font-medium text-[#333] mt-2">Skipped:</div>
                    <ul className="text-xs text-[#666] space-y-0.5">
                      {(sendResult as SendResult).skipped.map((r) => (
                        <li key={r.poster_id}>
                          {r.poster_id} — {r.reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {(sendResult as SendResult).errors.length > 0 && (
                  <div>
                    <div className="font-medium text-red-700 mt-2">Errors:</div>
                    <ul className="text-xs text-red-600 space-y-0.5">
                      {(sendResult as SendResult).errors.map((r) => (
                        <li key={r.poster_id}>
                          {r.poster_id} — {r.error}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* Preview modal */}
      <Dialog open={previewPoster !== null} onOpenChange={(open: boolean) => !open && setPreviewPoster(null)}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              Preview: {previewPoster?.poster_name}
            </DialogTitle>
          </DialogHeader>
          {previewPoster && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-3 text-sm">
                <Badge variant="secondary">
                  {previewPoster.song_count} songs
                </Badge>
                <Badge variant="secondary">
                  {previewPoster.page_count} pages with songs
                </Badge>
                {previewPoster.skipped_pages.length > 0 && (
                  <Badge variant="outline" className="border-amber-300 text-amber-700">
                    {previewPoster.skipped_pages.length} pages have no songs
                  </Badge>
                )}
              </div>

              <div className="bg-[#f7f7fa] rounded-md p-4 border border-[#e8e8ef]">
                <div className="text-xs uppercase text-[#888] tracking-wide mb-2">
                  Telegram message preview
                </div>
                <pre className="text-sm text-[#333] whitespace-pre-wrap font-mono">
                  {previewPoster.text}
                </pre>
              </div>

              {previewPoster.skipped_pages.length > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-md p-3 text-sm text-amber-900">
                  <div className="font-semibold mb-1">Pages with no active songs (won't appear in message):</div>
                  <ul className="list-disc list-inside space-y-0.5">
                    {previewPoster.skipped_pages.map((p) => (
                      <li key={p.integration_id}>{p.page_name}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setPreviewPoster(null)}>
                  Close
                </Button>
                <Button
                  onClick={() => {
                    const pid = previewPoster.poster_id
                    setPreviewPoster(null)
                    sendToPoster(pid)
                  }}
                  disabled={previewPoster.song_count === 0}
                >
                  <Send className="w-4 h-4 mr-2" />
                  Send Now
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
