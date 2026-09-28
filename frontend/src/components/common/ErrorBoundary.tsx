import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/Button'

/**
 * Keeps a render error inside one block: the block shows `fallback` and the rest of the page stays up. For content
 * whose shape comes from a service built separately (the assistant's cards, the second opinion), where a renamed
 * field must not take the whole app down with it.
 */
export class ErrorBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('a block failed to render', error, info.componentStack)
  }

  render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}

/** what a route shows in place of a page that failed: the plain facts and the two ways on */
export function RouteFallback({ onRetry }: { onRetry?: () => void }) {
  return (
    <div role="alert" className="mx-auto max-w-lg px-4 py-16 sm:px-6">
      <h1 className="text-xl font-semibold text-fg-base">This page could not be shown</h1>
      <p className="mt-2 text-sm text-fg-muted">
        Something in it failed to draw. Reloading usually clears it; if it keeps happening, tell your administrator
        and say which page it was.
      </p>
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={() => (onRetry ? onRetry() : window.location.reload())}>Reload</Button>
        <Link to="/" className="inline-flex h-9 items-center rounded-lg border border-border-default bg-surface-panel px-4 text-sm font-medium text-fg-base hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
          Go to Home
        </Link>
      </div>
    </div>
  )
}

/**
 * The boundary around the routes (App.tsx): a page — or its lazy chunk — that throws shows RouteFallback with a
 * Reload instead of a blank app. Keyed by the path in App, so going to another page starts clean; Reload asks the
 * browser for the page again, which also fetches a chunk the last deploy replaced.
 */
export class RouteErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('a page failed to render', error, info.componentStack)
  }

  render(): ReactNode {
    return this.state.failed ? <RouteFallback /> : this.props.children
  }
}
