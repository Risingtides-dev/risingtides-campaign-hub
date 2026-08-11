import type {
  CampaignSummary,
  CampaignDetail,
  MatchedVideo,
  CobrandStats,
  CampaignReport,
  CreatorSummary,
  CreatorProfile,
  InternalCreator,
  InternalGroup,
  InternalGroupDetail,
  InternalGroupStats,
  InternalScrapeResults,
  InternalSongResult,
  ScrapeStatus,
  ScrapeStartResponse,
  JobScrapeStatus,
  InboxItem,
  InboxCreator,
  ApiOk,
  SearchResult,
  BudgetResponse,
  NetworkCreator,
  OutreachResponse,
  OutreachStatusResponse,
  Tracker,
  TrackerGroup,
  ShareToken,
  ScrapeTaskQueue,
  ScrapeTaskHealth,
  BreakerLens,
  BreakerResponse,
  CreatorDrilldown,
  TargetSound,
  RebookSuggestion,
  LabelStats,
  BookerSummary,
  PosterSummary,
  BookerStats,
  CreatorRollup,
  LibraryResponse,
  LibraryNiche,
  LibraryCreator,
  LibraryRate,
  LibraryRefreshStatus,
  LibraryWindow,
  SoundFitResponse,
} from "./types"

const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:5055" : "")

class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
    this.name = "ApiError"
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }))
    throw new ApiError(body.error || res.statusText, res.status)
  }
  return res.json()
}

export const api = {
  // Campaigns
  // Fetches ALL campaigns (active + finished) — kept for pages that want the
  // full set in one call (tracker mapping, dropdowns). Note: /api/campaigns
  // defaults to active-only, so the finished set must be requested explicitly.
  getCampaigns: () => request<CampaignSummary[]>("/api/campaigns?include_finished=true"),

  // Split fetches for the campaigns list page: the Active tab is ~37 rows and
  // returns in ~200ms; the finished set is ~285 rows and pays the big query.
  // Loading them separately lets the page paint active campaigns immediately
  // instead of blocking first render on the slowest set (which is what made
  // the list page take seconds to show any data).
  getActiveCampaigns: () => request<CampaignSummary[]>("/api/campaigns"),
  getFinishedCampaigns: () => request<CampaignSummary[]>("/api/campaigns?active=false"),

  getCampaign: (slug: string) =>
    request<CampaignDetail>(`/api/campaign/${slug}`),

  createCampaign: (data: {
    title: string
    official_sound: string
    start_date: string
    budget: number
  }) =>
    request<ApiOk & { slug: string }>("/api/campaign/create", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  editCampaign: (slug: string, data: Record<string, unknown>) =>
    request<ApiOk>(`/api/campaign/${slug}/edit`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  refreshStats: (slug: string) =>
    request<ApiOk>(`/api/campaign/${slug}/refresh`, {
      method: "POST",
    }),

  getCampaignLinks: (slug: string) =>
    request<{
      videos: MatchedVideo[]
      scrape_log: Record<string, unknown>
    }>(`/api/campaign/${slug}/links`),

  searchCampaigns: (q: string) =>
    request<SearchResult>(`/api/search?q=${encodeURIComponent(q)}`),

  getBudget: (slug: string) =>
    request<BudgetResponse>(`/api/campaign/${slug}/budget`),

  // Creators
  addCreator: (
    slug: string,
    data: {
      username: string
      posts_owed: number
      total_rate: number
      paypal_email?: string
      platform?: string
    }
  ) =>
    request<ApiOk>(`/api/campaign/${slug}/creator/add`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  editCreator: (
    slug: string,
    username: string,
    data: Record<string, unknown>
  ) =>
    request<ApiOk>(`/api/campaign/${slug}/creator/${username}/edit`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  togglePaid: (slug: string, username: string) =>
    request<{ ok: boolean; paid: string; username: string }>(
      `/api/campaign/${slug}/creator/${username}/toggle-paid`,
      { method: "POST" }
    ),

  removeCreator: (slug: string, username: string) =>
    request<ApiOk>(
      `/api/campaign/${slug}/creator/${username}/remove`,
      { method: "POST" }
    ),

  getPaypal: (username: string) =>
    request<{ paypal: string }>(`/api/paypal/${username}`),

  // Creator Database
  getCreators: () => request<CreatorSummary[]>("/api/creators"),
  getCreatorProfile: (username: string) =>
    request<CreatorProfile>(`/api/creators/${username}`),

  // Creator Intelligence (sound-breaking analytics)
  getBreakers: (lens: BreakerLens = "balanced", limit = 100, minPosts = 5) =>
    request<BreakerResponse>(
      `/api/intelligence/breakers?lens=${lens}&limit=${limit}&min_posts=${minPosts}`
    ),
  getCreatorIntel: (account: string, withOutcomes = false) =>
    request<CreatorDrilldown>(
      `/api/intelligence/creator/${encodeURIComponent(account)}${withOutcomes ? "?outcomes=1" : ""}`
    ),
  getSounds: () =>
    request<{ sounds: TargetSound[] }>("/api/intelligence/sounds"),
  getRebookSuggestions: () =>
    request<{ suggestions: RebookSuggestion[] }>("/api/intelligence/rebook-suggestions"),
  getSoundFit: (soundId: string) =>
    request<SoundFitResponse>(
      `/api/intelligence/sound-fit/${encodeURIComponent(soundId)}`
    ),
  updateCreatorNiches: (username: string, niches: string[]) =>
    request<ApiOk & { updated: number; niches: string[] }>(
      `/api/creators/${username}/niches`,
      { method: "PATCH", body: JSON.stringify({ niches }) }
    ),

  // TidesTracker
  createTracker: (slug: string) =>
    request<ApiOk & { tracker_campaign_id: string; tracker_url: string }>(
      `/api/campaign/${slug}/create-tracker`,
      { method: "POST" }
    ),

  // Cobrand
  getCobrandStats: (slug: string) =>
    request<CobrandStats>(`/api/campaign/${slug}/cobrand`),
  getCampaignReport: (slug: string) =>
    request<CampaignReport>(`/api/campaign/${slug}/report`),
  getCreatorRollup: (username: string, days = 90) =>
    request<CreatorRollup>(`/api/creators/${encodeURIComponent(username)}/rollup?days=${days}`),
  // Attribution rollups (CAMP-34 / CAMP-38)
  getLabelStats: (days = 3650) =>
    request<{ labels: LabelStats[] }>(`/api/internal/labels?days=${days}`),
  getBookers: (days = 3650) =>
    request<{ bookers: BookerSummary[] }>(`/api/internal/bookers?days=${days}`),
  getPosters: (days = 3650) =>
    request<{ bookers: PosterSummary[] }>(`/api/internal/posters?days=${days}`),
  getBookerStats: (slug: string, days = 3650) =>
    request<BookerStats>(`/api/internal/bookers/${encodeURIComponent(slug)}/stats?days=${days}`),

  setCobrandLinks: (
    slug: string,
    data: { share_url?: string; upload_url?: string }
  ) =>
    request<ApiOk>(`/api/campaign/${slug}/cobrand`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // Internal
  getInternalCreators: () =>
    request<InternalCreator[]>("/api/internal/creators"),

  addInternalCreators: (username: string) =>
    request<ApiOk & { added: string[] }>("/api/internal/creators", {
      method: "POST",
      body: JSON.stringify({ username }),
    }),

  removeInternalCreator: (username: string) =>
    request<ApiOk>(`/api/internal/creators/${username}`, {
      method: "DELETE",
    }),

  triggerInternalScrape: (hours: number) =>
    request<ApiOk>("/api/internal/scrape", {
      method: "POST",
      body: JSON.stringify({ hours }),
    }),

  getInternalScrapeStatus: () =>
    request<ScrapeStatus>("/api/internal/scrape/status"),

  getInternalResults: () =>
    request<InternalScrapeResults>("/api/internal/results"),

  getInternalCreator: (username: string) =>
    request<{
      username: string
      total_videos: number
      total_videos_raw: number
      total_views: number
      total_likes: number
      songs: InternalSongResult[]
    }>(`/api/internal/creator/${username}`),

  getInternalGroups: () =>
    request<InternalGroup[]>("/api/internal/groups"),

  getInternalGroup: (slug: string) =>
    request<InternalGroupDetail>(`/api/internal/groups/${slug}`),

  getInternalGroupStats: (slug: string, days = 30) =>
    request<InternalGroupStats>(`/api/internal/groups/${slug}/stats?days=${days}`),

  getInternalFreshness: () =>
    request<{
      total_videos: number
      newest_upload_date: string | null
      newest_cached_at: string | null
      days_since_newest_upload: number | null
    }>("/api/internal/freshness"),

  triggerInternalScrapeAdvanced: (params: {
    hours?: number
    group?: string
    username?: string
    start_date?: string
    end_date?: string
  }) =>
    request<ApiOk & { creators_count: number }>("/api/internal/scrape", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  // Per-group scrape trigger (RTA-16)
  // Backend: POST /api/internal/scrape/start  body {group, hours}
  //   -> { job_id, started_at, debounced? }
  // Debounced=true means an existing in-flight job for this group was returned;
  // callers should poll the returned job_id rather than treat it as an error.
  startInternalScrape: (params: { group: string; hours?: number }) =>
    request<ScrapeStartResponse>("/api/internal/scrape/start", {
      method: "POST",
      body: JSON.stringify({
        group: params.group,
        hours: params.hours ?? 168,
      }),
    }),

  // Per-job poll for the /scrape/start trigger above.
  // Backend: GET /api/internal/scrape/status?job_id=<id>
  //   -> { state: "running"|"done"|"error", progress: {n,m}, last_log, error? }
  getInternalScrapeJobStatus: (job_id: string) =>
    request<JobScrapeStatus>(
      `/api/internal/scrape/status?job_id=${encodeURIComponent(job_id)}`
    ),

  // Inbox
  getInbox: (status?: string) =>
    request<InboxItem[]>(
      `/api/inbox${status ? `?status=${status}` : ""}`
    ),

  addInboxItem: (data: Record<string, unknown>) =>
    request<ApiOk & { id: string }>("/api/inbox", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  approveInbox: (
    id: string,
    data: { campaign_slug: string; creators: InboxCreator[] }
  ) =>
    request<ApiOk & { added: string[] }>(`/api/inbox/${id}/approve`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  dismissInbox: (id: string) =>
    request<ApiOk>(`/api/inbox/${id}/dismiss`, {
      method: "POST",
    }),

  // Notion sync
  syncNotion: () =>
    request<
      ApiOk & {
        created: Array<{ slug: string; title: string }>
        skipped: Array<{ slug: string; reason: string }>
      }
    >("/api/webhooks/notion/sync", { method: "POST" }),

  // Network
  getNetwork: () => request<NetworkCreator[]>("/api/network"),

  addNetworkCreator: (data: Record<string, unknown>) =>
    request<ApiOk & { creator: NetworkCreator }>("/api/network", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  editNetworkCreator: (username: string, data: Record<string, unknown>) =>
    request<ApiOk & { creator: NetworkCreator }>(`/api/network/${username}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  removeNetworkCreator: (username: string) =>
    request<ApiOk>(`/api/network/${username}`, { method: "DELETE" }),

  // Outreach
  getOutreach: (slug: string) =>
    request<OutreachResponse>(`/api/campaign/${slug}/outreach`),

  addToOutreach: (slug: string, creators: Array<{ username: string; rate: number; posts: number }>) =>
    request<ApiOk & { added: number }>(`/api/campaign/${slug}/outreach/add`, {
      method: "POST",
      body: JSON.stringify(creators),
    }),

  removeFromOutreach: (slug: string, username: string) =>
    request<ApiOk>(`/api/campaign/${slug}/outreach/remove`, {
      method: "POST",
      body: JSON.stringify({ username }),
    }),

  sendOutreach: (slug: string, data: { message_template: string; reference_post?: string }) =>
    request<{ ok: boolean; sent: string[]; errors: Array<{ username: string; error: string }> }>(
      `/api/campaign/${slug}/outreach/send`,
      { method: "POST", body: JSON.stringify(data) }
    ),

  getOutreachStatus: (slug: string) =>
    request<OutreachStatusResponse>(`/api/campaign/${slug}/outreach/status`),

  confirmOutreach: (slug: string, username: string) =>
    request<ApiOk>(`/api/campaign/${slug}/outreach/confirm`, {
      method: "POST",
      body: JSON.stringify({ username }),
    }),

  // TidesTrackers — list comes live from TidesTracker; groups are local
  listTrackers: (includeArchived = false) =>
    request<Tracker[]>(
      `/api/trackers${includeArchived ? "?include_archived=true" : ""}`
    ),

  createStandaloneTracker: (data: {
    name?: string
    cobrand_share_url: string
    group_id?: number | null
  }) =>
    request<{
      ok: boolean
      tracker: {
        id: string
        name: string
        cobrand_share_url: string
        tracker_url: string
        group_id: number | null
      }
    }>("/api/trackers", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  setTrackerGroup: (trackerId: string, groupId: number | null) =>
    request<{ ok: boolean; id: string; group_id: number | null }>(
      `/api/trackers/${trackerId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ group_id: groupId }),
      }
    ),

  setTrackerName: (trackerId: string, name: string | null) =>
    request<{ ok: boolean; id: string; name: string | null }>(
      `/api/trackers/${trackerId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ name }),
      }
    ),

  setTrackerCampaign: (trackerId: string, campaignSlug: string | null) =>
    request<{ ok: boolean; id: string; campaign_slug: string | null }>(
      `/api/trackers/${trackerId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ campaign_slug: campaignSlug }),
      }
    ),

  archiveTracker: (trackerId: string) =>
    request<{ ok: boolean; id: string; archived: boolean }>(
      `/api/trackers/${trackerId}`,
      { method: "DELETE" }
    ),

  restoreTracker: (trackerId: string) =>
    request<{ ok: boolean; id: string; archived: boolean }>(
      `/api/trackers/${trackerId}/restore`,
      { method: "POST" }
    ),

  listTrackerGroups: () => request<TrackerGroup[]>("/api/tracker-groups"),

  createTrackerGroup: (data: { title: string; slug?: string }) =>
    request<TrackerGroup>("/api/tracker-groups", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  deleteTrackerGroup: (id: number) =>
    request<ApiOk>(`/api/tracker-groups/${id}`, { method: "DELETE" }),

  // Share Tokens
  createShareToken: (slug: string, data: { label?: string; expires_days?: number }) =>
    request<{ ok: boolean; token: ShareToken; url: string }>(`/api/campaign/${slug}/share-token`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  listShareTokens: () =>
    request<ShareToken[]>("/api/share-tokens"),

  revokeShareToken: (token: string) =>
    request<ApiOk>(`/api/share-token/${token}`, { method: "DELETE" }),

  // Scrape Tasks tab
  getScrapeTaskQueue: (params?: { campaign?: string; since?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.campaign) qs.set("campaign", params.campaign)
    if (params?.since) qs.set("since", params.since)
    if (params?.limit != null) qs.set("limit", String(params.limit))
    const suffix = qs.toString() ? `?${qs.toString()}` : ""
    return request<ScrapeTaskQueue>(`/api/scrape-tasks/queue${suffix}`)
  },

  getScrapeTaskHealth: () => request<ScrapeTaskHealth>("/api/scrape-tasks/health"),

  markVideosTracked: (matched_video_ids: number[], tracked_by?: string) =>
    request<ApiOk & { marked_tracked: number; requested: number }>(
      "/api/scrape-tasks/mark-tracked",
      {
        method: "POST",
        body: JSON.stringify({ matched_video_ids, tracked_by: tracked_by || "" }),
      }
    ),

  unmarkVideosTracked: (matched_video_ids: number[]) =>
    request<ApiOk & { unmarked: number; requested: number }>(
      "/api/scrape-tasks/unmark-tracked",
      {
        method: "POST",
        body: JSON.stringify({ matched_video_ids }),
      }
    ),

  markCampaignTracked: (slug: string, tracked_by?: string) =>
    request<ApiOk & { slug: string; marked_tracked: number }>(
      "/api/scrape-tasks/mark-campaign-tracked",
      {
        method: "POST",
        body: JSON.stringify({ slug, tracked_by: tracked_by || "" }),
      }
    ),

  dismissVideos: (
    matched_video_ids: number[],
    opts?: { dismissed_by?: string; reason?: string }
  ) =>
    request<ApiOk & { dismissed: number; requested: number }>(
      "/api/scrape-tasks/dismiss",
      {
        method: "POST",
        body: JSON.stringify({
          matched_video_ids,
          dismissed_by: opts?.dismissed_by || "",
          reason: opts?.reason || "",
        }),
      }
    ),

  undismissVideos: (matched_video_ids: number[]) =>
    request<ApiOk & { undismissed: number; requested: number }>(
      "/api/scrape-tasks/undismiss",
      {
        method: "POST",
        body: JSON.stringify({ matched_video_ids }),
      }
    ),

  triggerCron: (job_type: "campaign_refresh" | "internal_scrape") =>
    request<{ status: string; job_type: string }>("/api/cron/trigger", {
      method: "POST",
      body: JSON.stringify({ job_type }),
    }),
  // CAMP-24/22: on-demand scrape trigger (job-tracked, non-blocking)
  triggerScrape: (body: { all_active?: boolean; campaign_id?: string }) =>
    request<{ job_id?: string; state: string; scope?: string; already_running?: boolean }>(
      "/api/scrape-tasks/trigger",
      { method: "POST", body: JSON.stringify(body) }
    ),
  scrapeTriggerStatus: (job_id?: string) =>
    request<{
      job_id?: string
      state: string
      scope?: string
      result?: unknown
      error?: string
      progress?: { done: number; total: number; last_account: string; pct: number }
    }>(
      `/api/scrape-tasks/trigger/status${job_id ? `?job_id=${encodeURIComponent(job_id)}` : ""}`
    ),
  // ── Creator Library ──────────────────────────────────────────────────
  // `key` (lowercased username) is the join key everywhere below; it is
  // encoded because handles legitimately contain dots and underscores.
  getLibrary: (window: LibraryWindow = "w60") =>
    request<LibraryResponse>(`/api/library/creators?window=${window}`),
  addLibraryCreator: (data: {
    username: string
    rate?: number | null
    niches?: string[]
    paypal_email?: string
  }) =>
    request<ApiOk & { username: string }>("/api/library/creators", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateLibraryCreator: (
    username: string,
    data: { rate?: number | null; slow?: boolean; note?: string; paypal_email?: string }
  ) =>
    request<ApiOk & { creator: LibraryCreator }>(
      `/api/library/creators/${encodeURIComponent(username)}`,
      { method: "PATCH", body: JSON.stringify(data) }
    ),
  setLibraryNiches: (username: string, niches: string[]) =>
    request<ApiOk & { niches: string[] }>(
      `/api/library/creators/${encodeURIComponent(username)}/niches`,
      { method: "PUT", body: JSON.stringify({ niches }) }
    ),
  getLibraryRate: (username: string) =>
    request<LibraryRate>(
      `/api/library/creators/${encodeURIComponent(username)}/rate`
    ),

  getNiches: () =>
    request<{ count: number; niches: LibraryNiche[] }>("/api/library/niches"),
  createNiche: (name: string) =>
    request<LibraryNiche>("/api/library/niches", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  renameNiche: (id: number, name: string) =>
    request<LibraryNiche>(`/api/library/niches/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  deleteNiche: (id: number) =>
    request<ApiOk>(`/api/library/niches/${id}`, { method: "DELETE" }),
  mergeNiche: (id: number, into: number) =>
    request<LibraryNiche>(`/api/library/niches/${id}/merge`, {
      method: "POST",
      body: JSON.stringify({ into }),
    }),
  /** Tag many creators at once — the bulk path for working the backlog. */
  applyNiche: (id: number, usernames: string[]) =>
    request<ApiOk & { tagged: number; requested: number }>(
      `/api/library/niches/${id}/apply`,
      { method: "POST", body: JSON.stringify({ usernames }) }
    ),
  /** Returns 202 immediately; the walk runs server-side. Poll
   *  getLibraryRefreshStatus for completion. */
  refreshLibraryStats: () =>
    request<{ status: string }>("/api/library/refresh-stats", {
      method: "POST",
    }),
  getLibraryRefreshStatus: () =>
    request<LibraryRefreshStatus>("/api/library/refresh-status"),
}

export { ApiError }
