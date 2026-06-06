import { Component, type ErrorInfo, type ReactNode } from "react"

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * App-level error boundary (CAMP-79). Catches render-time crashes that would
 * otherwise blank the whole app, and shows a recoverable fallback instead of a
 * white screen. Pairs with the QueryClient onError toasts for async failures.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the trace visible in dev/console for debugging.
    console.error("Uncaught render error:", error, info.componentStack)
  }

  handleReset = () => {
    this.setState({ error: null })
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-background p-6">
          <div className="max-w-md rounded-2xl border border-white/8 bg-rt-bg-card p-8 text-center">
            <div className="text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">
              Something broke
            </div>
            <h1 className="mt-2 font-display text-2xl font-bold text-rt-fg">
              This view hit an error
            </h1>
            <p className="mt-3 text-sm text-rt-fg-secondary">
              The page crashed while rendering. Your data is safe — try again, or
              reload if it persists.
            </p>
            <pre className="mt-4 max-h-32 overflow-auto rounded-lg bg-rt-bg-black p-3 text-left text-[11px] text-rt-fg-tertiary">
              {this.state.error.message}
            </pre>
            <div className="mt-5 flex justify-center gap-3">
              <button
                onClick={this.handleReset}
                className="rounded-lg rt-gradient-bg px-4 py-2 text-sm font-medium text-white"
              >
                Try again
              </button>
              <button
                onClick={() => window.location.reload()}
                className="rounded-lg border border-white/10 px-4 py-2 text-sm text-rt-fg-secondary hover:bg-white/5"
              >
                Reload
              </button>
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
