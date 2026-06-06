import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import {
  QueryClient,
  QueryClientProvider,
  MutationCache,
  QueryCache,
} from "@tanstack/react-query"
import { toast } from "sonner"
import "./index.css"
import App from "./App.tsx"
import { ErrorBoundary } from "./components/ErrorBoundary"

// CAMP-79: global error net. Before this, failed mutations/queries gave the
// user zero feedback — a spinner stopped, a row reverted, and it looked like a
// no-op (or a page rendered "no data" masking the error). These onError
// handlers surface any UNHANDLED failure as a toast, and the ErrorBoundary
// below catches render-time crashes.
function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  return fallback
}

// De-dupe rapid identical toasts (a failing poller would otherwise stack one
// per tick). Suppress the same message within a short window.
const _recentToasts = new Map<string, number>()
function toastOnce(message: string) {
  const now = Date.now()
  const last = _recentToasts.get(message)
  if (last && now - last < 8000) return
  _recentToasts.set(message, now)
  toast.error(message)
}

const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      // Don't double-toast: if the mutation defines its own onError, it already
      // surfaces a (usually more specific) message. The global net is only for
      // mutations that would otherwise fail silently.
      if (mutation.options.onError) return
      toastOnce(errorMessage(error, "Something went wrong saving your change."))
    },
  }),
  queryCache: new QueryCache({
    // Only toast background/refetch failures here — page components still show
    // their own inline error states for the initial load. This catches the
    // silent ones (a refetch that fails after the page already rendered).
    onError: (error, query) => {
      // Skip polling queries (refetchInterval) — they'd toast every tick on a
      // backend hiccup. Their components own their status display.
      if ((query.options as { refetchInterval?: unknown }).refetchInterval) return
      if (query.state.data !== undefined) {
        toastOnce(errorMessage(error, "Couldn't refresh — showing cached data."))
      }
    },
  }),
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
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>
)
