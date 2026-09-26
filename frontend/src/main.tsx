import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Lenis from 'lenis'
import './index.css'
import App from './App'

// ── Lenis Smooth Scroll Initialisation ────────────────────────────────────
// Smooth, normalized scroll across browsers.
// Must not interfere with keyboard navigation or accessibility tree.
const lenis = new Lenis({
  duration: 1.2,
  easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
  touchMultiplier: 2,
  infinite: false,
})

function raf(time: number): void {
  lenis.raf(time)
  requestAnimationFrame(raf)
}
requestAnimationFrame(raf)

// ── TanStack Query Client ──────────────────────────────────────────────────
// retry: false — mock engine never fails; no network retries needed.
// staleTime: 5min — data is stable within a session.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
})

// ── React Root ────────────────────────────────────────────────────────────
const rootEl = document.getElementById('root')
if (!rootEl) {
  throw new Error('[PAIMANA] Root element #root not found in DOM. Check index.html.')
}

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>
)
