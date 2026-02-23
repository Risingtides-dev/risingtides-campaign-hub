import { useState } from "react"
import { Outlet } from "react-router-dom"
import { Menu } from "lucide-react"
import { Sidebar } from "./Sidebar"

export function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="flex min-h-screen bg-[#f7f7f9] text-[#1a1a2e]">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex-1 md:ml-[220px] min-w-0">
        {/* Mobile header */}
        <div className="md:hidden flex items-center gap-3 p-4 bg-white border-b border-[#e8e8ef]">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1 rounded hover:bg-[#f0f0f5]"
          >
            <Menu className="w-6 h-6 text-[#555]" />
          </button>
          <span className="text-lg font-bold text-[#1a1a2e]">Campaign Tracker</span>
        </div>

        <main className="p-6 md:px-8 md:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
