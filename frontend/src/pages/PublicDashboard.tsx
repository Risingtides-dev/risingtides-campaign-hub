import { useState, useMemo, useEffect } from "react"
import { useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { fetchDashboard, downloadCsv } from "@/lib/public-api"
import type { PublicDashboardData, PublicPost, PublicCreator } from "@/lib/types"
import {
  Eye, Heart, MessageCircle, Share2, TrendingUp, Video,
  Download, ArrowUpDown, ChevronDown, Loader2, AlertCircle,
  ExternalLink, User,
} from "lucide-react"

// -- Recharts imports (lazy-loaded via dynamic import or direct) --
// Users must run: npm install recharts
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts"

type SortOption = "newest" | "most_viewed" | "most_liked" | "most_shared"

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

function formatDate(dateStr: string): string {
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

// =====================================================================
// Stat Card Component
// =====================================================================

function StatCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string
  value: string
  icon: React.ComponentType<{ className?: string }>
  color: string
}) {
  return (
    <div className="bg-white border border-[#e8e8ef] rounded-xl p-5">
      <div className="flex items-center gap-2 mb-2">
        <Icon className={`size-4 ${color}`} />
        <span className="text-[#888] text-[11px] font-semibold uppercase tracking-wider">
          {label}
        </span>
      </div>
      <div className="text-[26px] font-bold text-[#1a1a2e]">{value}</div>
    </div>
  )
}

// =====================================================================
// Post Card Component
// =====================================================================

function PostCard({ post }: { post: PublicPost }) {
  return (
    <a
      href={post.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group block bg-white border border-[#e8e8ef] rounded-xl overflow-hidden hover:border-[#6B21A8]/30 hover:shadow-md transition-all"
    >
      {/* Thumbnail */}
      <div className="aspect-[9/16] bg-gradient-to-br from-[#1a1a2e] to-[#6B21A8] relative overflow-hidden">
        {post.thumbnail_url ? (
          <img
            src={post.thumbnail_url}
            alt={`Post by ${post.account}`}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Video className="size-10 text-white/30" />
          </div>
        )}
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors flex items-center justify-center">
          <ExternalLink className="size-6 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>
        {/* Platform badge */}
        <div className="absolute top-2 right-2 bg-black/50 text-white text-[10px] font-semibold px-2 py-0.5 rounded-full uppercase">
          {post.platform}
        </div>
      </div>
      {/* Info */}
      <div className="p-3">
        <div className="text-sm font-medium text-[#1a1a2e] truncate">
          @{post.account}
        </div>
        <div className="flex items-center gap-3 mt-1.5 text-[12px] text-[#888]">
          <span className="flex items-center gap-1">
            <Eye className="size-3" />
            {formatNumber(post.views)}
          </span>
          <span className="flex items-center gap-1">
            <Heart className="size-3" />
            {formatNumber(post.likes)}
          </span>
        </div>
        {post.upload_date && (
          <div className="text-[11px] text-[#aaa] mt-1">
            {formatDate(post.upload_date)}
          </div>
        )}
      </div>
    </a>
  )
}

// =====================================================================
// Creator Card Component
// =====================================================================

function CreatorCard({ creator }: { creator: PublicCreator }) {
  return (
    <div className="flex flex-col items-center bg-white border border-[#e8e8ef] rounded-xl p-4 min-w-[140px]">
      {creator.profile_pic_url ? (
        <img
          src={creator.profile_pic_url}
          alt={creator.username}
          className="size-14 rounded-full object-cover border-2 border-[#e8e8ef]"
        />
      ) : (
        <div className="size-14 rounded-full bg-gradient-to-br from-[#6B21A8] to-[#1a1a2e] flex items-center justify-center">
          <User className="size-6 text-white/70" />
        </div>
      )}
      <div className="mt-2 text-sm font-medium text-[#1a1a2e] truncate max-w-full">
        @{creator.username}
      </div>
      <div className="flex items-center gap-3 mt-1 text-[12px] text-[#888]">
        <span>{creator.posts_done} posts</span>
        <span>{formatNumber(creator.total_views)} views</span>
      </div>
    </div>
  )
}

// =====================================================================
// Main Public Dashboard Page
// =====================================================================

export default function PublicDashboard() {
  const { token } = useParams<{ token: string }>()
  const [sortBy, setSortBy] = useState<SortOption>("newest")
  const [filterCreator, setFilterCreator] = useState<string>("all")
  const [activeRound, setActiveRound] = useState<string>("all")

  const { data, isLoading, isError, error } = useQuery<PublicDashboardData>({
    queryKey: ["public-dashboard", token],
    queryFn: () => fetchDashboard(token!),
    enabled: !!token,
    staleTime: 60_000,
  })

  // Set page title
  useEffect(() => {
    if (data?.title) {
      document.title = `${data.title} - Rising Tides`
    }
    return () => {
      document.title = "Rising Tides Campaign Hub"
    }
  }, [data?.title])

  // Sort and filter posts
  const filteredPosts = useMemo(() => {
    if (!data?.posts) return []
    let posts = [...data.posts]

    // Filter by round
    if (activeRound !== "all") {
      posts = posts.filter((p) => p.round === activeRound)
    }

    // Filter by creator
    if (filterCreator !== "all") {
      posts = posts.filter((p) => p.account === filterCreator)
    }

    // Sort
    switch (sortBy) {
      case "newest":
        posts.sort((a, b) => (b.upload_date || "").localeCompare(a.upload_date || ""))
        break
      case "most_viewed":
        posts.sort((a, b) => b.views - a.views)
        break
      case "most_liked":
        posts.sort((a, b) => b.likes - a.likes)
        break
      case "most_shared":
        posts.sort((a, b) => b.shares - a.shares)
        break
    }

    return posts
  }, [data?.posts, sortBy, filterCreator, activeRound])

  // Unique creators for filter dropdown
  const creatorNames = useMemo(() => {
    if (!data?.posts) return []
    return [...new Set(data.posts.map((p) => p.account))].sort()
  }, [data?.posts])

  // Loading state
  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#f9f9fb] flex items-center justify-center">
        <div className="flex items-center gap-3">
          <Loader2 className="size-6 animate-spin text-[#6B21A8]" />
          <span className="text-[#888] text-sm">Loading dashboard...</span>
        </div>
      </div>
    )
  }

  // Error state
  if (isError || !data) {
    return (
      <div className="min-h-screen bg-[#f9f9fb] flex items-center justify-center">
        <div className="bg-white border border-[#e8e8ef] rounded-xl p-10 text-center max-w-md">
          <AlertCircle className="size-10 text-red-400 mx-auto mb-4" />
          <h2 className="text-lg font-semibold text-[#1a1a2e] mb-2">
            Dashboard Unavailable
          </h2>
          <p className="text-[#888] text-sm">
            {(error as Error)?.message || "This share link may be expired or invalid."}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#f9f9fb]">
      {/* Header */}
      <header className="bg-white border-b border-[#e8e8ef]">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="size-9 bg-gradient-to-br from-[#6B21A8] to-[#1a1a2e] rounded-lg flex items-center justify-center">
                <TrendingUp className="size-5 text-white" />
              </div>
              <span className="text-[15px] font-semibold text-[#1a1a2e] tracking-tight">
                Rising Tides
              </span>
            </div>
            <button
              onClick={() => downloadCsv(token!)}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-[#6B21A8] bg-[#6B21A8]/5 border border-[#6B21A8]/20 rounded-lg hover:bg-[#6B21A8]/10 transition-colors"
            >
              <Download className="size-4" />
              Export CSV
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-8">
        {/* Campaign Title Section */}
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-[#1a1a2e]">
            {data.title}
          </h1>
          <div className="flex items-center gap-3 mt-2 text-sm text-[#888]">
            {data.artist && <span>{data.artist}</span>}
            {data.artist && data.song && <span className="text-[#ddd]">|</span>}
            {data.song && <span>{data.song}</span>}
            {data.created_at && (
              <>
                <span className="text-[#ddd]">|</span>
                <span>{formatDate(data.created_at)}</span>
              </>
            )}
          </div>
        </div>

        {/* Round Filter Tabs */}
        {data.rounds.length > 1 && (
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            <button
              onClick={() => setActiveRound("all")}
              className={`px-4 py-1.5 text-sm font-medium rounded-full border transition-colors whitespace-nowrap ${
                activeRound === "all"
                  ? "bg-[#6B21A8] text-white border-[#6B21A8]"
                  : "bg-white text-[#666] border-[#e8e8ef] hover:border-[#6B21A8]/30"
              }`}
            >
              All Rounds
            </button>
            {data.rounds.map((round) => (
              <button
                key={round}
                onClick={() => setActiveRound(round)}
                className={`px-4 py-1.5 text-sm font-medium rounded-full border transition-colors whitespace-nowrap ${
                  activeRound === round
                    ? "bg-[#6B21A8] text-white border-[#6B21A8]"
                    : "bg-white text-[#666] border-[#e8e8ef] hover:border-[#6B21A8]/30"
                }`}
              >
                {round}
              </button>
            ))}
          </div>
        )}

        {/* Tab Bar */}
        <div className="border-b border-[#e8e8ef]">
          <div className="flex gap-6">
            <button className="pb-3 text-sm font-semibold text-[#6B21A8] border-b-2 border-[#6B21A8]">
              Live Post Analytics
            </button>
          </div>
        </div>

        {/* Stat Cards Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <StatCard
            label="Total Views"
            value={formatNumber(data.stats.total_views)}
            icon={Eye}
            color="text-blue-500"
          />
          <StatCard
            label="Total Likes"
            value={formatNumber(data.stats.total_likes)}
            icon={Heart}
            color="text-red-400"
          />
          <StatCard
            label="Total Comments"
            value={formatNumber(data.stats.total_comments)}
            icon={MessageCircle}
            color="text-amber-500"
          />
          <StatCard
            label="Total Shares"
            value={formatNumber(data.stats.total_shares)}
            icon={Share2}
            color="text-green-500"
          />
          <StatCard
            label="Engagement"
            value={`${data.stats.engagement_pct.toFixed(1)}%`}
            icon={TrendingUp}
            color="text-[#6B21A8]"
          />
          <StatCard
            label="Live Posts"
            value={data.stats.live_post_count.toString()}
            icon={Video}
            color="text-[#1a1a2e]"
          />
        </div>

        {/* Stats Over Time Chart */}
        {data.stats_history.length > 1 && (
          <div className="bg-white border border-[#e8e8ef] rounded-xl p-5">
            <h3 className="text-sm font-semibold text-[#1a1a2e] mb-4">
              Performance Over Time
            </h3>
            <div className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.stats_history}>
                  <defs>
                    <linearGradient id="viewsGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#6B21A8" stopOpacity={0.15} />
                      <stop offset="95%" stopColor="#6B21A8" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="likesGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.1} />
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11, fill: "#888" }}
                    tickFormatter={(v) => {
                      try {
                        return new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric" })
                      } catch {
                        return v
                      }
                    }}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#888" }}
                    tickFormatter={(v) => formatNumber(v)}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#fff",
                      border: "1px solid #e8e8ef",
                      borderRadius: "8px",
                      fontSize: "13px",
                    }}
                    formatter={(value: number, name: string) => [
                      formatNumber(value),
                      name.charAt(0).toUpperCase() + name.slice(1),
                    ]}
                    labelFormatter={(label) => {
                      try {
                        return new Date(label).toLocaleDateString("en-US", {
                          month: "long",
                          day: "numeric",
                          year: "numeric",
                        })
                      } catch {
                        return label
                      }
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="views"
                    stroke="#6B21A8"
                    strokeWidth={2}
                    fill="url(#viewsGradient)"
                  />
                  <Area
                    type="monotone"
                    dataKey="likes"
                    stroke="#ef4444"
                    strokeWidth={2}
                    fill="url(#likesGradient)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* Creator List */}
        {data.creators.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-[#1a1a2e] mb-3">
              Creators ({data.creators.length})
            </h3>
            <div className="flex gap-3 overflow-x-auto pb-2">
              {data.creators.map((creator) => (
                <CreatorCard key={creator.username} creator={creator} />
              ))}
            </div>
          </div>
        )}

        {/* Post Thumbnails Section */}
        <div>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
            <h3 className="text-sm font-semibold text-[#1a1a2e]">
              Posts ({filteredPosts.length})
            </h3>
            <div className="flex items-center gap-2 flex-wrap">
              {/* Sort buttons */}
              {(
                [
                  ["newest", "Newest"],
                  ["most_viewed", "Most Viewed"],
                  ["most_liked", "Most Liked"],
                  ["most_shared", "Most Shared"],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setSortBy(key)}
                  className={`px-3 py-1 text-[12px] font-medium rounded-full border transition-colors ${
                    sortBy === key
                      ? "bg-[#1a1a2e] text-white border-[#1a1a2e]"
                      : "bg-white text-[#666] border-[#e8e8ef] hover:border-[#999]"
                  }`}
                >
                  {label}
                </button>
              ))}

              {/* Creator filter */}
              {creatorNames.length > 1 && (
                <div className="relative">
                  <select
                    value={filterCreator}
                    onChange={(e) => setFilterCreator(e.target.value)}
                    className="appearance-none pl-3 pr-8 py-1 text-[12px] font-medium rounded-full border border-[#e8e8ef] bg-white text-[#666] cursor-pointer hover:border-[#999] transition-colors"
                  >
                    <option value="all">All Creators</option>
                    {creatorNames.map((name) => (
                      <option key={name} value={name}>
                        @{name}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="size-3 text-[#888] absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              )}
            </div>
          </div>

          {filteredPosts.length === 0 ? (
            <div className="bg-white border border-[#e8e8ef] rounded-xl p-10 text-center">
              <Video className="size-8 text-[#ccc] mx-auto mb-2" />
              <p className="text-[#888] text-sm">No posts yet</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
              {filteredPosts.map((post) => (
                <PostCard key={post.url} post={post} />
              ))}
            </div>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-[#e8e8ef] mt-12">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="size-6 bg-gradient-to-br from-[#6B21A8] to-[#1a1a2e] rounded flex items-center justify-center">
              <TrendingUp className="size-3.5 text-white" />
            </div>
            <span className="text-[13px] font-medium text-[#888]">
              Rising Tides
            </span>
          </div>
          <span className="text-[12px] text-[#aaa]">Campaign Analytics Dashboard</span>
        </div>
      </footer>
    </div>
  )
}
