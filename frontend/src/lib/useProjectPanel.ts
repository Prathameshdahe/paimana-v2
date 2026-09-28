import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** the element that had focus when the side panel opened: it gets focus back when the panel closes */
let opener: Element | null = null

/**
 * Remember what opened the panel (the focused lane, row or link), so closing it returns there instead of to the page's
 * top. Nothing is remembered for the page body or for an element inside the panel itself (moving to another project
 * from within keeps the first opener).
 */
export function rememberOpener(
  active: Element | null = typeof document === 'undefined' ? null : document.activeElement,
): void {
  if (!active || active === active.ownerDocument?.body) return
  if (active.closest?.('[role="dialog"]')) return
  opener = active
}

/** give focus back to the remembered opener while it is still on the page; true when it took focus */
export function restoreOpener(): boolean {
  const el = opener as (Element & { focus?: (o?: FocusOptions) => void }) | null
  opener = null
  if (!el || !el.isConnected || typeof el.focus !== 'function') return false
  el.focus({ preventScroll: true })
  return true
}

/**
 * The project side panel (views/command-center/ProjectDetailDrawer, mounted once in App) opens on
 * ?project=KEY, so any list on any page opens it with open(key) and a copied link keeps it open.
 */
export function useProjectPanel() {
  const [params, setParams] = useSearchParams()
  const open = useCallback(
    (key: string) => {
      rememberOpener()
      setParams((p) => { p.set('project', key); return p }, { replace: true })
    },
    [setParams]
  )
  const close = useCallback(
    () => setParams((p) => { p.delete('project'); return p }, { replace: true }),
    [setParams]
  )
  return { key: params.get('project'), open, close }
}
