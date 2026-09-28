import { Suspense, lazy } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { ChatWidget } from '@/components/common/ChatWidget'
import { SessionProvider, useSession } from '@/lib/auth/SessionContext'
import { RequireRole } from '@/lib/auth/RequireRole'

const Home = lazy(() => import('@/views/Home').then(m => ({ default: m.Home })))
const CommandCenter = lazy(() => import('@/views/CommandCenter').then(m => ({ default: m.CommandCenter })))
const ProjectStudio = lazy(() => import('@/views/ProjectStudio').then(m => ({ default: m.ProjectStudio })))
const ExternalFactors = lazy(() => import('@/views/ExternalFactors').then(m => ({ default: m.ExternalFactors })))
const Models = lazy(() => import('@/views/Models').then(m => ({ default: m.Models })))
const Login = lazy(() => import('@/views/Login').then(m => ({ default: m.Login })))
const WorkerConsole = lazy(() => import('@/views/WorkerConsole').then(m => ({ default: m.WorkerConsole })))
const ApprovalInbox = lazy(() => import('@/views/ApprovalInbox').then(m => ({ default: m.ApprovalInbox })))
const Agencies = lazy(() => import('@/views/Agencies').then(m => ({ default: m.Agencies })))
const Bottlenecks = lazy(() => import('@/views/Bottlenecks').then(m => ({ default: m.Bottlenecks })))
const Radar = lazy(() => import('@/views/Radar').then(m => ({ default: m.Radar })))
// its own chunk (recharts, motion): the main bundle does not wait for it
const ProjectDetailDrawer = lazy(() => import('@/views/command-center/ProjectDetailDrawer').then(m => ({ default: m.ProjectDetailDrawer })))

/** the account pages stand alone: no top bar, no side panel, no assistant */
const BARE = new Set(['/login'])

const Loading = () => (
  <div className="flex h-48 items-center justify-center text-xs text-fg-dimmed">loading…</div>
)

export default function App() {
  return (
    <SessionProvider>
      <TooltipProvider>
        <Shell />
      </TooltipProvider>
    </SessionProvider>
  )
}

function Shell() {
  const location = useLocation()
  const bare = BARE.has(location.pathname)
  // the routes wait for GET /api/auth/me, so an official never sees the public page flash before their own
  const { status } = useSession()

  return (
    <div className="min-h-dvh bg-surface-base text-fg-base font-sans antialiased selection:bg-accent/30 selection:text-fg-base flex flex-col">
      {!bare && <TopBar />}

      <main className={bare ? 'flex-1' : 'flex-1 pb-16'}>
        <Suspense fallback={<Loading />}>
          {status === 'loading' ? <Loading /> : (
            <Routes>
              {/* Who opens which page: lib/auth/access.ts (ROUTE_ROLES); the public browses without signing in */}
              <Route path="/" element={<Home />} />
              <Route path="/login" element={<Login />} />

              {/* Project list + search (DETECT); read-only for the public */}
              <Route path="/command" element={<RequireRole><CommandCenter /></RequireRole>} />
              {/* Project page (DIAGNOSE); the public gets the simple one */}
              <Route path="/projects/:key" element={<RequireRole><ProjectStudio /></RequireRole>} />
              {/* External Factors — land, forest, litigation, contractor; replaces the what-if sandbox */}
              <Route path="/external" element={<RequireRole><ExternalFactors /></RequireRole>} />
              <Route path="/sandbox" element={<Navigate to="/external" replace />} />

              {/* Officials: Bottleneck Intelligence (guide §6.1), Agency Matrix (§6.3), Evidence Radar (§6.2), approvals */}
              <Route path="/bottlenecks" element={<RequireRole><Bottlenecks /></RequireRole>} />
              <Route path="/agencies" element={<RequireRole><Agencies /></RequireRole>} />
              <Route path="/radar" element={<RequireRole><Radar /></RequireRole>} />
              <Route path="/approvals" element={<RequireRole><ApprovalInbox /></RequireRole>} />

              {/* Models (PROVE): ministry + IPMD; was /audit */}
              <Route path="/models" element={<RequireRole><Models /></RequireRole>} />
              <Route path="/audit" element={<Navigate to="/models" replace />} />

              {/* Worker Console: IPMD only */}
              <Route path="/workers" element={<RequireRole><WorkerConsole /></RequireRole>} />

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          )}
        </Suspense>
      </main>

      {/* the project side panel, opened from any list with useProjectPanel (?project=KEY) */}
      {!bare && <Suspense fallback={null}><ProjectDetailDrawer /></Suspense>}

      {/* the project assistant, for every role (lib/auth/access.ts canChat); the backend scopes each tool to the viewer */}
      {!bare && <ChatWidget />}
    </div>
  )
}
