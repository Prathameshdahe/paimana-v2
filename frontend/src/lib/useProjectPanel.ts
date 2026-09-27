import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * The project side panel (views/command-center/ProjectDetailDrawer, mounted once in App) opens on
 * ?project=KEY, so any list on any page opens it with open(key) and a copied link keeps it open.
 */
export function useProjectPanel() {
  const [params, setParams] = useSearchParams()
  const open = useCallback(
    (key: string) => setParams((p) => { p.set('project', key); return p }, { replace: true }),
    [setParams]
  )
  const close = useCallback(
    () => setParams((p) => { p.delete('project'); return p }, { replace: true }),
    [setParams]
  )
  return { key: params.get('project'), open, close }
}
