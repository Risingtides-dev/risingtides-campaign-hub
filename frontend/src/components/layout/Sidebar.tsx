import { Link, useLocation } from "react-router-dom"

const navItems = [
  {
    section: "Campaigns",
    links: [{ label: "Promotions", path: "/" }],
  },
  {
    section: "Creators",
    links: [{ label: "Creator Database", path: "/creators" }],
  },
  {
    section: "Internal",
    links: [{ label: "Internal TikTok", path: "/internal" }],
  },
  {
    section: "Outreach",
    links: [{ label: "Outreach Hub", path: "/network" }],
  },
  {
    section: "Intake",
    links: [{ label: "Slack Inbox", path: "/inbox" }],
  },
  {
    section: "Tracking",
    links: [{ label: "TidesTrackers", path: "/trackers" }],
  },
  {
    section: "Distribution",
    links: [{ label: "Sound Assignments", path: "/sound-assignments" }],
  },
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
        className={`fixed top-0 left-0 bottom-0 z-50 w-[220px] bg-white border-r border-[#e8e8ef] py-6 overflow-y-auto transition-transform duration-200 md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="px-6 pb-6 border-b border-[#e8e8ef]">
          <span className="text-xl font-bold text-[#1a1a2e]">Campaign Tracker</span>
        </div>

        {navItems.map((group) => (
          <div key={group.section}>
            <div className="pt-4 pb-1 px-6 text-[11px] font-semibold uppercase tracking-[0.5px] text-[#999]">
              {group.section}
            </div>
            {group.links.map((link) => (
              <Link
                key={link.path}
                to={link.path}
                onClick={onClose}
                className={`flex items-center gap-2.5 px-6 py-2.5 text-sm transition-colors ${
                  isActive(link.path)
                    ? "bg-[#eef2ff] text-[#0b62d6] font-semibold border-l-[3px] border-[#0b62d6] pl-[21px]"
                    : "text-[#555] hover:bg-[#f0f0f5]"
                }`}
              >
                {link.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>
    </>
  )
}
