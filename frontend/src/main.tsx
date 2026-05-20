import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import "./index.css"
import App from "./App.tsx"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 5 min default staleness — cuts perceived "constant refetching" when
      // navigating between pages. Hooks that need shorter staleness (e.g.
      // scrape-task queue, scrape-job polling) override per-query.
      staleTime: 5 * 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
      // Don't refetch on remount if cache is still fresh — combined with the
      // 5-min staleTime above, this is what eliminates the per-nav refetch.
      // Per-query refetchInterval (polling) is unaffected.
      refetchOnMount: false,
    },
  },
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
)
