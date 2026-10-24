import { useEffect, useRef } from 'react'
import { observeSemanticSurface } from '../services/api'
import type { CanvasResourceRef } from '@promethea/sdk'
import { useAuth } from '../store/AuthContext'

/** Report host-visible references, never guessed intentions or iframe-provided facts. */
export function useEnvironmentObservation(view: string, objects: CanvasResourceRef[] = [], enabled = true) {
  const { user } = useAuth()
  const identity = useRef(crypto.randomUUID())
  const sequence = useRef(0)
  const descriptor = JSON.stringify({ view, objects })
  useEffect(() => {
    if (!user || !enabled) return
    const source = JSON.parse(descriptor) as { view: string; objects: CanvasResourceRef[] }
    const controller = new AbortController()
    const report = (closed = false) => {
      void observeSemanticSurface({ ...source, surface_id: identity.current, sequence: ++sequence.current,
        visible: !closed && document.visibilityState === 'visible', focused: !closed && document.hasFocus(),
      }, closed ? undefined : controller.signal).catch(() => {})
    }
    const changed = () => report()
    const leaving = () => report(true)
    report()
    const timer = window.setInterval(changed, 20000)
    document.addEventListener('visibilitychange', changed)
    window.addEventListener('focus', changed)
    window.addEventListener('blur', changed)
    window.addEventListener('pagehide', leaving)
    return () => {
      controller.abort()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', changed)
      window.removeEventListener('focus', changed)
      window.removeEventListener('blur', changed)
      window.removeEventListener('pagehide', leaving)
      report(true)
    }
  }, [descriptor, enabled, user?.user_id])
}
