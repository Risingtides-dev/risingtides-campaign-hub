// Campaign types
export interface CampaignBudget {
  total: number
  booked: number
  paid: number
  left: number
  pct: number
}

export interface CampaignStats {
  live_posts: number
  total_views: number
  cpm: number | null
}

export interface CampaignSummary {
  slug: string
  title: string
  artist: string
  song: string
  start_date: string
  status: string
  completion_status: "none" | "booked" | "completed"
  budget: CampaignBudget
  stats: CampaignStats
  creator_count: number
}

export interface Creator {
  username: string
  posts_owed: number
  posts_done: number
  posts_matched: number
  total_rate: number
  per_post_rate: number
  paypal_email: string
  paid: string
  payment_date: string
  platform: string
  added_date: string
  status: string
  notes: string
  niches: string[]
}

export interface CampaignDetail {
  slug: string
  title: string
  artist: string
  song: string
  sound_id: string
  official_sound: string
  tt_artist_label: string
  tt_track_name: string
  additional_sounds: string[]
  cobrand_link: string
  cobrand_share_url: string
  cobrand_upload_url: string
  start_date: string
  budget: CampaignBudget
  stats: CampaignStats
  creators: Creator[]
  matched_videos: MatchedVideo[]
  platform: string
  status: string
  source: string
  label: string
  round: string
  campaign_stage: string
  project_lead: string[]
  client_email: string
  platform_split: Record<string, number>
  content_types: string[]
  tracker_campaign_id?: string
  tracker_url?: string
}

export interface MatchedVideo {
  url: string
  song: string
  artist: string
  account: string
  views: number
  likes: number
  upload_date: string
  timestamp: string
  music_id: string
  platform: string
  extracted_sound_id: string
  extracted_song_title: string
}

// Cobrand types
export interface CobrandSound {
  id_platform: string
  platform: string
  title: string
}

export interface CobrandActivation {
  id: string
  name: string
  artist_name: string
  artist_image_url: string
  social_sounds: CobrandSound[]
  created_at: string
  draft_submission_due_at: string | null
  final_submission_due_at: string | null
  tags: string[]
}

export interface CobrandStats {
  promotion_id: string
  name: string
  status: string
  live_submission_count: number
  draft_submission_count: number
  comment_count: number
  activation_count: number
  created_at: string
  activations: CobrandActivation[]
}

// Internal TikTok types
export interface InternalCreator {
  username: string
  total_videos: number
  total_views: number
}

export interface InternalGroup {
  id: number
  slug: string
  title: string
  kind: string
  sort_order: number
  member_count: number
  created_at: string
}

export interface InternalGroupDetail extends InternalGroup {
  members: string[]
}

export interface InternalGroupStats {
  group: InternalGroup
  days: number
  total_posts: number
  total_views: number
  total_likes: number
  creators: { username: string; posts: number; views: number; likes: number }[]
  top_songs: { song: string; artist: string; posts: number; views: number }[]
}

export interface InternalVideo {
  url: string
  song: string
  artist: string
  account: string
  views: number
  likes: number
  upload_date: string
}

export interface InternalSongResult {
  key: string
  song: string
  artist: string
  total_views: number
  total_likes: number
  accounts: string[]
  videos: InternalVideo[]
}

export interface InternalScrapeResults {
  scraped_at: string
  hours: number
  start_dt: string
  end_dt: string
  accounts_total: number
  accounts_successful: number
  accounts_failed: number
  total_videos: number
  total_videos_unfiltered: number
  unique_songs: number
  songs: InternalSongResult[]
}

export interface ScrapeAccountLog {
  username: string
  status: "ok" | "failed"
  video_count: number
  error?: string
}

export interface ScrapeStatus {
  running: boolean
  progress: string
  done: boolean
  accounts_total: number
  accounts_completed: number
  accounts_failed: number
  videos_so_far: number
  current_accounts: string[]
  log: ScrapeAccountLog[]
}

// Inbox types
export interface InboxCreator {
  username: string
  posts_owed: number
  total_rate: number
  paypal_email?: string
  paid?: string
  notes?: string
}

export interface InboxItem {
  id: string
  created_at: string
  status: string
  source: string
  raw_message: string
  campaign_name: string
  campaign_slug: string
  campaign_suggested: boolean
  creators: InboxCreator[]
  notes: string
  approved_at?: string
  dismissed_at?: string
  creators_added?: string[]
}

// Creator Database types
export interface CreatorProfile {
  username: string
  platform: string
  paypal_email: string
  stats: {
    campaigns_count: number
    total_posts_owed: number
    total_posts_done: number
    total_spend: number
    total_payout: number
    total_views: number
    total_likes: number
    avg_cpm: number | null
  }
  campaigns: CreatorCampaignEntry[]
  videos: CreatorVideo[]
}

export interface CreatorCampaignEntry {
  slug: string
  title: string
  artist: string
  song: string
  posts_owed: number
  posts_done: number
  total_rate: number
  paid: string
  payment_date: string
  status: string
  notes: string
}

export interface CreatorVideo {
  url: string
  campaign_slug: string
  campaign_title: string
  views: number
  likes: number
  upload_date: string
}

export interface CreatorSummary {
  username: string
  campaigns_count: number
  total_posts_owed: number
  total_posts_done: number
  total_spend: number
  total_payout: number
  total_views: number
  avg_cpm: number | null
  platform: string
  paypal_email: string
  niches: string[]
}

// Network & Outreach types
export interface NetworkCreator {
  username: string
  platform: string
  default_rate: number
  default_posts: number
  paypal_email: string
  manychat_subscriber_id: string
  niches: string[]
  notes: string
  added_at: string
  in_outreach?: boolean
}

export interface OutreachMessage {
  id: number
  campaign_id: number
  username: string
  rate_offered: number
  posts_offered: number
  message_text: string
  status: "draft" | "sent" | "responded" | "accepted" | "declined" | "expired" | "posted" | "verified"
  sent_at: string
  responded_at: string
  manychat_message_id: string
  reply_text: string
  notes: string
}

export interface OutreachResponse {
  campaign: Record<string, unknown>
  messages: OutreachMessage[]
  network_creators: NetworkCreator[]
  templates: Record<string, string>
}

export interface OutreachStatusResponse {
  messages: OutreachMessage[]
  counts: Record<string, number>
}

// Public Dashboard types
export interface PublicStats {
  total_views: number
  total_likes: number
  total_shares: number
  total_comments: number
  engagement_pct: number
  live_post_count: number
}

export interface PublicCreator {
  username: string
  profile_pic_url: string
  posts_done: number
  total_views: number
}

export interface PublicPost {
  url: string
  thumbnail_url: string
  account: string
  views: number
  likes: number
  shares: number
  comments: number
  upload_date: string
  platform: string
  round: string
}

export interface StatsHistoryPoint {
  date: string
  views: number
  likes: number
  posts: number
}

export interface PublicDashboardData {
  title: string
  artist: string
  song: string
  created_at: string
  rounds: string[]
  stats: PublicStats
  creators: PublicCreator[]
  posts: PublicPost[]
  stats_history: StatsHistoryPoint[]
}

export interface ShareToken {
  id: number
  campaign_id: number | null
  token: string
  label: string
  campaign_slugs: string[]
  round_filter: string
  created_at: string
  expires_at: string | null
  is_active: boolean
  last_accessed: string | null
  access_count: number
}

// API response wrappers
export interface ApiOk {
  ok: boolean
  message: string
}

export interface SearchResult {
  query: string
  results: CampaignSummary[]
}

export interface BudgetResponse {
  title: string
  slug: string
  budget_total: number
  budget_booked: number
  budget_paid: number
  budget_remaining: number
  budget_pct_used: number
  message: string
}

// TidesTrackers
export interface TrackerGroup {
  id: number
  slug: string
  title: string
  sort_order: number
  created_at: string
  tracker_count: number
}

export interface TrackerClient {
  id: string
  name: string
  slug: string
}

export interface TrackerCampaignRef {
  slug: string
  title: string
}

export interface Tracker {
  id: string                       // TidesTracker UUID
  name: string                     // local override if set, else original
  original_name: string            // raw name from TidesTracker
  slug: string
  cobrand_share_url: string
  tracker_url: string
  is_active: boolean
  created_at: string
  client: TrackerClient | null
  group_id: number | null          // local overlay
  campaign_slug: string | null     // local overlay
  campaign: TrackerCampaignRef | null
}
