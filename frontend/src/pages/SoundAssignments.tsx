import { useCallback, useEffect, useMemo, useState } from "react"
import { Search, RefreshCw, Send, Eye, AlertTriangle, X, Music, CheckCircle2, Loader2, CheckCheck, CircleSlash } from "lucide-react"
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

// ---- Telegram HTML preview renderer ----

// The lab returns the message body in Telegram-flavored HTML. We render
// just the two tags it actually uses (<b>, <a href="...">), plus the few
// entities (&amp; &lt; &gt; &quot;), so the preview matches what the
// poster will see in Telegram. We deliberately do NOT use
// dangerouslySetInnerHTML on raw API output.
function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
}

type PreviewNode =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "link"; text: string; href: string }

function parseTelegramHtml(html: string): PreviewNode[] {
  const nodes: PreviewNode[] = []
  // Combined regex for <b>...</b> and <a href="...">...</a> in source order.
  const re = /<b>([\s\S]*?)<\/b>|<a\s+href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g
  let cursor = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    if (m.index > cursor) {
      nodes.push({ kind: "text", text: decodeEntities(html.slice(cursor, m.index)) })
    }
    if (m[1] !== undefined) {
      nodes.push({ kind: "bold", text: decodeEntities(m[1]) })
    } else if (m[2] !== undefined && m[3] !== undefined) {
      nodes.push({ kind: "link", text: decodeEntities(m[3]), href: decodeEntities(m[2]) })
    }
    cursor = m.index + m[0].length
  }
  if (cursor < html.length) {
    nodes.push({ kind: "text", text: decodeEntities(html.slice(cursor)) })
  }
  return nodes
}

function TelegramPreview({ html }: { html: string }) {
  const nodes = useMemo(() => parseTelegramHtml(html), [html])
  return (
    <div className="text-sm text-[#333] whitespace-pre-wrap font-sans leading-relaxed">
      {nodes.map((n, i) => {
        if (n.kind === "bold") return <strong key={i} className="font-semibold text-[#1a1a2e]">{n.text}</strong>
        if (n.kind === "link") return (
          <a
            key={i}
            href={n.href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#0b62d6] hover:underline"
          >
            {n.text}
          </a>
        )
        return <span key={i}>{n.text}</span>
      })}
    </div>
  )
}

// ---- API client ----

// Honor VITE_API_URL when defined (including empty string for relative URLs
// via Vite dev proxy). Only fall back to localhost when the var is absent.
const API_BASE = import.meta.env.VITE_API_URL !== undefined
  ? import.meta.env.VITE_API_URL
  : (import.meta.env.DEV ? "http://localhost:5055" : "")

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

  // Sound-first model: pick a sound, then check posters to assign that
  // sound to every page that poster owns. Page list is read-only/admin
  // visibility — checking happens at the poster level.
  const [selectedSound, setSelectedSound] = useState<string | null>(null)
  const [soundFilter, setSoundFilter] = useState("")
  const [pageFilter, setPageFilter] = useState("")
  // Per-poster in-flight save indicator (the row checkbox toggles all
  // of that poster's pages, so the spinner sits on the poster row).
  const [savingPosterId, setSavingPosterId] = useState<string | null>(null)
  // Top-bar "Select all / Clear all" in-flight indicator.
  const [bulkPostering, setBulkPostering] = useState(false)

  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [previewPoster, setPreviewPoster] = useState<PosterPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [sendingPoster, setSendingPoster] = useState<string | null>(null)
  const [sendingAll, setSendingAll] = useState(false)
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

  // For each sound id, the set of page_ids that have it assigned. Drives
  // the checkbox state in the right column AND the smart-expand decision.
  const pagesBySoundId = useMemo(() => {
    const m: Record<string, Set<string>> = {}
    for (const [pageId, soundIds] of Object.entries(playlists)) {
      for (const sid of soundIds) {
        if (!m[sid]) m[sid] = new Set<string>()
        m[sid].add(pageId)
      }
    }
    return m
  }, [playlists])

  // ---- Sound pool: active only + newest first + filter ----

  const visibleSounds = useMemo(() => {
    const q = soundFilter.trim().toLowerCase()
    return sounds
      .filter((s) => s.active !== false)
      .filter((s) => (q ? s.label.toLowerCase().includes(q) : true))
      .sort((a, b) => {
        // Newest first. added_at is ISO-ish; fall back to string compare.
        const av = a.added_at || ""
        const bv = b.added_at || ""
        if (av === bv) return 0
        return av < bv ? 1 : -1
      })
  }, [sounds, soundFilter])

  // ---- Mutations ----

  // Toggle the selected sound across ALL of a poster's pages in one motion.
  // Checking the poster row = assign sound to every page they own.
  // Unchecking = remove from every page they own.
  async function togglePosterForSound(posterId: string) {
    if (!selectedSound) return
    const poster = posters.find((p) => p.poster_id === posterId)
    if (!poster) return
    const assignedPages = pagesBySoundId[selectedSound] || new Set<string>()
    // If the poster has the sound on AT LEAST ONE page, treat the row as
    // "checked" and the click means "remove from all". Otherwise add to all.
    const anyAssigned = poster.page_ids.some((pid) => assignedPages.has(pid))
    setSavingPosterId(posterId)
    setError(null)
    try {
      const results = await Promise.all(
        poster.page_ids.map(async (pageId) => {
          const has = (playlists[pageId] || []).includes(selectedSound)
          // Skip API calls that would be no-ops.
          if (anyAssigned && !has) return { pageId, sound_ids: playlists[pageId] || [] }
          if (!anyAssigned && has) return { pageId, sound_ids: playlists[pageId] || [] }
          const url = anyAssigned
            ? `/pages/${pageId}/playlist/songs/${selectedSound}`
            : `/pages/${pageId}/playlist/songs`
          const r = await api<{ sound_ids: string[] }>(url, {
            method: anyAssigned ? "DELETE" : "POST",
            body: anyAssigned ? undefined : JSON.stringify({ sound_id: selectedSound }),
          })
          return { pageId, sound_ids: r.sound_ids }
        }),
      )
      setPlaylists((prev) => {
        const next = { ...prev }
        for (const { pageId, sound_ids } of results) next[pageId] = sound_ids
        return next
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed")
    } finally {
      setSavingPosterId(null)
    }
  }

  // Top-bar bulk toggle: Select All / Clear All posters for the selected sound.
  // If every poster already has the sound on at least one of their pages, treat
  // the action as "clear all" (remove from every page everywhere). Otherwise
  // assign the sound to every page of every poster that doesn't already have
  // it. Fan out per-page like the single-poster path.
  async function toggleAllPostersForSound() {
    if (!selectedSound) return
    if (posters.length === 0) return
    const assignedPages = pagesBySoundId[selectedSound] || new Set<string>()
    // Are we already at "all-on"? Every poster has at least one page assigned.
    const allOn = posters.every((p) => p.page_ids.some((pid) => assignedPages.has(pid)))
    setBulkPostering(true)
    setError(null)
    try {
      // Build the list of (pageId, action) calls we need.
      const tasks: { pageId: string; assign: boolean }[] = []
      for (const poster of posters) {
        for (const pageId of poster.page_ids) {
          const has = (playlists[pageId] || []).includes(selectedSound)
          if (allOn && has) tasks.push({ pageId, assign: false })
          else if (!allOn && !has) tasks.push({ pageId, assign: true })
        }
      }
      const results = await Promise.all(
        tasks.map(async ({ pageId, assign }) => {
          const url = assign
            ? `/pages/${pageId}/playlist/songs`
            : `/pages/${pageId}/playlist/songs/${selectedSound}`
          const r = await api<{ sound_ids: string[] }>(url, {
            method: assign ? "POST" : "DELETE",
            body: assign ? JSON.stringify({ sound_id: selectedSound }) : undefined,
          })
          return { pageId, sound_ids: r.sound_ids }
        }),
      )
      setPlaylists((prev) => {
        const next = { ...prev }
        for (const { pageId, sound_ids } of results) next[pageId] = sound_ids
        return next
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bulk toggle failed")
    } finally {
      setBulkPostering(false)
    }
  }

  async function syncSounds() {
    setSyncing(true)
    setError(null)
    try {
      const result = await api<SyncResult>("/sync", { method: "POST" })
      setLastSync(result)
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

  // ---- Right column derived data ----

  const selectedSoundObj = selectedSound ? soundById[selectedSound] : null
  const assignedPageIds = selectedSound ? pagesBySoundId[selectedSound] || new Set<string>() : new Set<string>()
  // "all-on" = every poster has the selected sound on at least one of their pages.
  // Drives the Select-All / Clear-All button label in the top bar.
  const allPostersAssigned = useMemo(() => {
    if (!selectedSound || posters.length === 0) return false
    return posters.every((p) => p.page_ids.some((pid) => assignedPageIds.has(pid)))
  }, [selectedSound, posters, assignedPageIds])

  // Filter posters' pages by pageFilter and collect counts. Only posters
  // with matching pages are visible after filtering.
  const visiblePosterGroups = useMemo(() => {
    const q = pageFilter.trim().toLowerCase()
    return posters.map((poster) => {
      const ownedPages = poster.page_ids
        .map((pid) => pageById[pid])
        .filter((p): p is RosterPage => Boolean(p))
      const matched = q
        ? ownedPages.filter((p) => p.name.toLowerCase().includes(q))
        : ownedPages
      const assignedCount = ownedPages.filter((p) => assignedPageIds.has(p.integration_id)).length
      return {
        poster,
        pages: matched,
        totalPages: ownedPages.length,
        assignedCount,
        hidden: q.length > 0 && matched.length === 0,
      }
    })
  }, [posters, pageById, pageFilter, assignedPageIds])

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
            Pick a sound, then check the pages that should run it. Posters get a daily message with their assignments.
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
            variant="outline"
            onClick={toggleAllPostersForSound}
            disabled={!selectedSound || bulkPostering}
            title={!selectedSound ? "Pick a sound on the left first" : ""}
          >
            {bulkPostering ? (
              <Loader2 className="w-4 h-4 animate-spin mr-2" />
            ) : allPostersAssigned ? (
              <CircleSlash className="w-4 h-4 mr-2" />
            ) : (
              <CheckCheck className="w-4 h-4 mr-2" />
            )}
            {allPostersAssigned ? "Clear All Posters" : "Select All Posters"}
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

      {/* Two-column layout: Sound Pool (left) | Pages-by-poster (right) */}
      <div className="grid grid-cols-1 md:grid-cols-[minmax(280px,360px)_1fr] gap-4 min-h-[600px]">
        {/* ---- Sound Pool ---- */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Music className="w-4 h-4" />
              Sound Pool ({visibleSounds.length})
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
            <div className="max-h-[640px] overflow-y-auto space-y-1 -mx-1 px-1">
              {visibleSounds.map((sound) => {
                const isSelected = selectedSound === sound.id
                const assignedCount = (pagesBySoundId[sound.id] || new Set()).size
                return (
                  <button
                    key={sound.id}
                    onClick={() => setSelectedSound(sound.id)}
                    className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center gap-2 ${
                      isSelected
                        ? "bg-[#eef2ff] text-[#0b62d6] font-semibold border border-[#c8d4ff]"
                        : "hover:bg-[#f0f0f5] text-[#333] border border-transparent"
                    }`}
                  >
                    <span className="truncate flex-1">{sound.label}</span>
                    {assignedCount > 0 && (
                      <Badge variant="secondary" className="text-xs shrink-0">
                        {assignedCount}
                      </Badge>
                    )}
                  </button>
                )
              })}
              {visibleSounds.length === 0 && (
                <div className="text-sm text-[#888] italic px-3 py-3 text-center">
                  {soundFilter ? "No sounds match filter" : "No active sounds — click Sync Sounds"}
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* ---- Pages by poster ---- */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center justify-between gap-2">
              <span className="truncate">
                {selectedSoundObj ? (
                  <>
                    Assign &ldquo;<span className="text-[#0b62d6]">{selectedSoundObj.label}</span>&rdquo; to pages
                  </>
                ) : (
                  "Pages"
                )}
              </span>
              {selectedSound && (
                <Badge variant="secondary" className="text-xs shrink-0">
                  {assignedPageIds.size} {assignedPageIds.size === 1 ? "page" : "pages"} assigned
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {!selectedSound && (
              <div className="text-sm text-[#888] italic px-3 py-12 text-center">
                Select a sound on the left to start assigning pages.
              </div>
            )}

            {selectedSound && (
              <>
                <div className="relative">
                  <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#888]" />
                  <Input
                    placeholder="Filter pages..."
                    value={pageFilter}
                    onChange={(e) => setPageFilter(e.target.value)}
                    className="pl-9"
                  />
                </div>

                <div className="max-h-[640px] overflow-y-auto space-y-3 -mx-1 px-1">
                  {visiblePosterGroups.map(({ poster, pages: groupPages, totalPages, assignedCount, hidden }) => {
                    if (hidden) return null
                    // Row check is on if at least one of the poster's pages
                    // has the sound. Toggling fans out across all their pages.
                    const isChecked = assignedCount > 0
                    const isPartial = assignedCount > 0 && assignedCount < totalPages
                    const isSaving = savingPosterId === poster.poster_id
                    return (
                      <div key={poster.poster_id} className="rounded-md border border-[#e8e8ef]">
                        {/* Poster row — single checkbox controls the whole roster */}
                        <label
                          className={`flex items-center justify-between gap-3 px-3 py-2.5 cursor-pointer hover:bg-[#f7f7fa] rounded-t-md ${isSaving ? "opacity-60" : ""}`}
                        >
                          <span className="flex items-center gap-3 flex-1 min-w-0">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              ref={(el) => { if (el) el.indeterminate = isPartial }}
                              disabled={isSaving}
                              onChange={() => togglePosterForSound(poster.poster_id)}
                              className="w-4 h-4 rounded border-[#ccc] text-[#0b62d6] focus:ring-[#0b62d6]"
                            />
                            <span className="text-sm font-semibold text-[#1a1a2e] truncate">{poster.name}</span>
                            {!poster.sounds_topic_id && (
                              <span title="No Sounds topic yet — will auto-create on first send">
                                <AlertTriangle className="w-3 h-3 text-amber-500 shrink-0" />
                              </span>
                            )}
                            {isSaving && <Loader2 className="w-3 h-3 animate-spin text-[#888] shrink-0" />}
                          </span>
                          <Badge
                            variant={assignedCount > 0 ? "default" : "secondary"}
                            className={`text-xs shrink-0 ${assignedCount > 0 ? "bg-green-100 text-green-800 border-green-200 hover:bg-green-100" : ""}`}
                          >
                            {assignedCount}/{totalPages}
                          </Badge>
                        </label>

                        {/* Read-only page list for admin visibility */}
                        <div className="border-t border-[#e8e8ef] bg-[#fafafd]">
                          {groupPages.length === 0 && (
                            <div className="px-3 py-2 text-xs text-[#888] italic">
                              No pages match the filter.
                            </div>
                          )}
                          {groupPages.map((page) => {
                            const pageHasSound = assignedPageIds.has(page.integration_id)
                            return (
                              <div
                                key={page.integration_id}
                                className="flex items-center gap-2 px-3 py-1.5 text-xs text-[#666]"
                              >
                                <span
                                  className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${pageHasSound ? "bg-green-500" : "bg-[#d8d8e0]"}`}
                                />
                                <span className="truncate">{page.name}</span>
                              </div>
                            )
                          })}
                        </div>

                        {/* Per-poster preview/send actions */}
                        <div className="border-t border-[#e8e8ef] flex gap-2 px-3 py-2">
                          <Button
                            variant="outline"
                            size="sm"
                            className="text-xs"
                            onClick={() => openPreview(poster.poster_id)}
                            disabled={previewLoading}
                          >
                            {previewLoading ? (
                              <Loader2 className="w-3 h-3 animate-spin mr-1" />
                            ) : (
                              <Eye className="w-3 h-3 mr-1" />
                            )}
                            Preview
                          </Button>
                          <Button
                            size="sm"
                            className="text-xs"
                            onClick={() => sendToPoster(poster.poster_id)}
                            disabled={sendingPoster === poster.poster_id || !status?.sounds_bot_running}
                            title={!status?.sounds_bot_running ? "Sounds bot must be running to send" : ""}
                          >
                            {sendingPoster === poster.poster_id ? (
                              <Loader2 className="w-3 h-3 animate-spin mr-1" />
                            ) : (
                              <Send className="w-3 h-3 mr-1" />
                            )}
                            Send to {poster.name}
                          </Button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </>
            )}
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
                <TelegramPreview html={previewPoster.text} />
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
