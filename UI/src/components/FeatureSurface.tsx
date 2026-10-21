import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

export type FeatureSurfaceProps = { embedded?: boolean; onClose: () => void }

export default function FeatureSurface({ embedded = false, onClose, label, children, size = 'wide' }: FeatureSurfaceProps & { label: string; children: ReactNode; size?: 'compact' | 'wide' }) {
  const ref = useRef<HTMLElement>(null)
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose }, [onClose])
  useEffect(() => {
    if (embedded) return
    const previous = document.activeElement as HTMLElement | null
    const root = ref.current
    const focusable = () => Array.from(root?.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href],[tabindex="0"]') || []).filter((item) => item.getClientRects().length > 0)
    if (!root?.contains(document.activeElement)) (focusable()[0] || root)?.focus()
    const keydown = (event: KeyboardEvent) => {
      const dialogs = document.querySelectorAll('[role="dialog"][aria-modal="true"]')
      if (dialogs[dialogs.length - 1] !== root) return
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current() }
      if (event.key !== 'Tab') return
      const items = focusable()
      const first = items[0]
      const last = items[items.length - 1]
      if (!first) { event.preventDefault(); root?.focus(); return }
      if (!root?.contains(document.activeElement)) { event.preventDefault(); (event.shiftKey ? last : first).focus() }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.removeEventListener('keydown', keydown); previous?.focus() }
  }, [embedded])

  return <div className={embedded ? 'feature-page' : 'feature-overlay'} onClick={embedded ? undefined : (event) => { if (event.target === event.currentTarget) onClose() }}>
    <section ref={ref} tabIndex={-1} role={embedded ? 'region' : 'dialog'} aria-modal={embedded ? undefined : true} aria-label={label} className={`feature-surface ${embedded ? 'is-page' : ''} surface-${size}`}>{children}</section>
  </div>
}
