import { useState } from "react"
import { Outlet } from "react-router-dom"
import { Menu } from "lucide-react"
import { Sidebar } from "./Sidebar"
import { Toaster } from "@/components/ui/sonner"

export function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex-1 md:ml-[220px] min-w-0">
        {/* Mobile header */}
        <div className="md:hidden flex items-center gap-3 p-4 bg-rt-bg-raised border-b border-white/8">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1 rounded hover:bg-white/5"
          >
            <Menu className="w-6 h-6 text-rt-fg-secondary" />
          </button>
          <span className="text-lg font-bold font-display text-rt-fg">Campaign Tracker</span>
        </div>

        <main className="p-6 md:px-8 md:py-6">
          <Outlet />
        </main>
      </div>

      {/* Global toast notifications */}
      <Toaster />
    </div>
  )
}
