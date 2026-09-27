import { Suspense, lazy } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { ChatWidget } from '@/components/common/ChatWidget'
import { RoleProvider } from '@/lib/auth/RoleContext'
import { RequireRole } from '@/lib/auth/RequireRole'

const Home = lazy(() => import('@/views/Home').then(m => ({ default: m.Home })))
const CommandCenter = lazy(() => import('@/views/CommandCenter').then(m => ({ default: m.CommandCenter })))
const ProjectStudio = lazy(() => import('@/views/ProjectStudio').then(m => ({ default: m.ProjectStudio })))
const PrescriptiveSandbox = lazy(() => import('@/views/PrescriptiveSandbox').then(m => ({ default: m.PrescriptiveSandbox })))
const AuditSuite = lazy(() => import('@/views/AuditSuite').then(m => ({ default: m.AuditSuite })))
const Login = lazy(() => import('@/views/Login').then(m => ({ default: m.Login })))
const WorkerConsole = lazy(() => import('@/views/WorkerConsole').then(m => ({ default: m.WorkerConsole })))
const ApprovalInbox = lazy(() => import('@/views/ApprovalInbox').then(m => ({ default: m.ApprovalInbox })))

export default function App() {
  const location = useLocation()
  const isLogin = location.pathname === '/login'

  return (
    <RoleProvider>
    <TooltipProvider>
      <div className="min-h-dvh bg-surface-base text-fg-base font-sans antialiased selection:bg-accent/30 selection:text-fg-base flex flex-col">
        {/* Persistent TopBar on every route except the full-bleed login screen */}
        {!isLogin && <TopBar />}

        {/* Dynamic Route Content */}
        <main className={isLogin ? 'flex-1' : 'flex-1 pb-16'}>
          <Suspense fallback={
            <div className="h-48 flex items-center justify-center font-mono text-xs text-fg-dimmed">
              loading module...
            </div>
          }>
            <Routes>
              {/* Route 0: Landing — map + early warning inbox. Public, no role required. */}
              <Route path="/" element={<Home />} />

              {/* Prototype role picker */}
              <Route path="/login" element={<Login />} />

              {/* Route 1: Executive Command Center (DETECT) */}
              <Route path="/command" element={<RequireRole roles={['ipmd_analyst', 'ministry_official', 'agency_official']}><CommandCenter /></RequireRole>} />

              {/* Route 2: Project Deep-Dive Studio (DIAGNOSE) */}
              <Route path="/projects/:id" element={<RequireRole roles={['ipmd_analyst', 'ministry_official', 'agency_official']}><ProjectStudio /></RequireRole>} />

              {/* Route 3: Prescriptive What-If Sandbox (PRESCRIBE) */}
              <Route path="/sandbox" element={<RequireRole roles={['ipmd_analyst', 'ministry_official', 'agency_official']}><PrescriptiveSandbox /></RequireRole>} />

              {/* Route 4: MoSPI Compliance & Audit Suite (PROVE) */}
              <Route path="/audit" element={<RequireRole roles={['ipmd_analyst', 'ministry_official', 'agency_official']}><AuditSuite /></RequireRole>} />

              {/* Route 5: Worker Console — IPMD analyst + ministry official only */}
              <Route
                path="/workers"
                element={
                  <RequireRole roles={['ipmd_analyst', 'ministry_official']}>
                    <WorkerConsole />
                  </RequireRole>
                }
              />

              {/* Route 6: Approval Inbox — everyone except public */}
              <Route
                path="/approvals"
                element={
                  <RequireRole roles={['ipmd_analyst', 'ministry_official', 'agency_official']}>
                    <ApprovalInbox />
                  </RequireRole>
                }
              />

              {/* Fallback to Command Center */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </main>

        {!isLogin && <ChatWidget />}
      </div>
    </TooltipProvider>
    </RoleProvider>
  )
}
