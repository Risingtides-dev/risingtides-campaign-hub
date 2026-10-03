import { useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { ChevronRight } from "lucide-react"

const navItems = [
  {
    section: "Campaigns",
    links: [
      { label: "Promotions", path: "/" },
      { label: "Scrape Tasks", path: "/scrape-tasks" },
    ],
  },
  {
    section: "Creators",
    links: [
      { label: "Creator Library", path: "/library" },
      { label: "Creator Database", path: "/creators" },
      { label: "Creator Intelligence", path: "/intelligence" },
      { label: "Booking Wizard", path: "/booking-wizard" },
      { label: "Booking Efficiency", path: "/efficiency" },
    ],
  },
  {
    section: "Outreach",
    links: [{ label: "Outreach Hub", path: "/network" }],
  },
  {
    section: "Tracking",
    links: [{ label: "TidesTrackers", path: "/trackers" }],
  },
]

// Low-traffic sections tucked behind a collapsed "Other" group so they
// don't clutter the sidebar (john, 08-07). They render only when the
// group is expanded.
const otherItems = [
  { label: "Rising Tides Tracker", path: "/rt-tracker" },
  { label: "Internal TikTok", path: "/internal" },
  { label: "Slack Inbox", path: "/inbox" },
  { label: "Sound Assignments", path: "/sound-assignments" },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const location = useLocation()

  const isActive = (path: string) => {
    if (path === "/") return location.pathname === "/" || location.pathname.startsWith("/campaign/")
    return location.pathname.startsWith(path)
  }

  // Start expanded when the current route lives inside "Other", so the
  // active link is never invisible.
  const [showOther, setShowOther] = useState(() =>
    otherItems.some((l) => isActive(l.path))
  )

  const renderLink = (link: { label: string; path: string }) => (
    <Link
      key={link.path}
      to={link.path}
      onClick={onClose}
      className={`flex items-center gap-2.5 px-6 py-2.5 text-sm transition-colors ${
        isActive(link.path)
          ? "bg-rt-magenta/10 text-rt-fg font-semibold border-l-[3px] border-rt-magenta pl-[21px]"
          : "text-rt-fg-secondary hover:bg-white/5 hover:text-rt-fg"
      }`}
    >
      {link.label}
    </Link>
  )

  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={onClose}
        />
      )}

      <nav
        className={`fixed top-0 left-0 bottom-0 z-50 w-[220px] bg-rt-bg-raised border-r border-white/8 py-6 overflow-y-auto transition-transform duration-200 md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="px-6 pb-6 border-b border-white/8">
          <span className="text-xl font-bold font-display rt-gradient-text">Campaign Hub</span>
        </div>

        {navItems.map((group) => (
          <div key={group.section}>
            <div className="pt-4 pb-1 px-6 text-[11px] font-semibold uppercase tracking-[0.12em] text-rt-fg-tertiary">
              {group.section}
            </div>
            {group.links.map(renderLink)}
          </div>
        ))}

        {/* Collapsed "Other" group */}
        <div>
          <button
            type="button"
            onClick={() => setShowOther((v) => !v)}
            className="w-full flex items-center gap-1 pt-4 pb-1 px-6 text-[11px] font-semibold uppercase tracking-[0.12em] text-rt-fg-tertiary hover:text-rt-fg transition-colors"
          >
            Other
            <ChevronRight
              className={`size-3 transition-transform ${showOther ? "rotate-90" : ""}`}
            />
          </button>
          {showOther && otherItems.map(renderLink)}
        </div>
      </nav>
    </>
  )
}
