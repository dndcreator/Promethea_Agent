import { useCallback, useEffect, useRef } from 'react'
import { observeSemanticSurface } from '../services/api'
import type { CanvasResourceRef } from '@promethea/sdk'
import { useAuth } from '../store/AuthContext'

/** Report host-visible references, never guessed intentions or iframe-provided facts. */
export function useEnvironmentObservation(view: string, objects: CanvasResourceRef[] = [], enabled = true, attention?: { component_id: string; definition_revision: string } | null) {
  const { user } = useAuth()
  const identity = useRef(crypto.randomUUID())
  const sequence = useRef(0)
  const root = useRef<HTMLElement | null>(null)
  const attach = useCallback((node: HTMLElement | null) => {
    root.current = node
    if (node) node.dataset.environmentSurface = identity.current
  }, [])
  const descriptor = JSON.stringify({ view, objects, active_component_id: attention?.component_id, definition_revision: attention?.definition_revision })
  useEffect(() => {
    if (!user || !enabled) return
    const source = JSON.parse(descriptor)
    const controller = new AbortController()
    let focused = !!root.current && document.activeElement?.closest('[data-environment-surface]') === root.current
    const report = (closed = false) => {
      void observeSemanticSurface({ ...source, surface_id: identity.current, sequence: ++sequence.current,
        visible: !closed && document.visibilityState === 'visible' && !!root.current?.getClientRects().length,
        focused: !closed && focused && document.hasFocus(),
      }, closed ? undefined : controller.signal).catch(() => {})
    }
    const changed = () => report()
    const locate = (event: Event) => {
      const target = event.target instanceof Element ? event.target : document.activeElement
      const next = !!root.current && target?.closest('[data-environment-surface]') === root.current
      if (next !== focused) { focused = next; report() }
    }
    const windowFocus = () => {
      focused = !!root.current && document.activeElement?.closest('[data-environment-surface]') === root.current
      report()
    }
    const leaving = () => report(true)
    report()
    const timer = window.setInterval(changed, 20000)
    document.addEventListener('visibilitychange', changed)
    document.addEventListener('pointerdown', locate, true)
    document.addEventListener('focusin', locate, true)
    window.addEventListener('focus', windowFocus)
    window.addEventListener('blur', windowFocus)
    window.addEventListener('pagehide', leaving)
    return () => {
      controller.abort()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', changed)
      document.removeEventListener('pointerdown', locate, true)
      document.removeEventListener('focusin', locate, true)
      window.removeEventListener('focus', windowFocus)
      window.removeEventListener('blur', windowFocus)
      window.removeEventListener('pagehide', leaving)
      report(true)
    }
  }, [descriptor, enabled, user?.user_id])
  return attach
}
