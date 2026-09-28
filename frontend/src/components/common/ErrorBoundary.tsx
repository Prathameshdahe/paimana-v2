import { Component, type ErrorInfo, type ReactNode } from 'react'

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
