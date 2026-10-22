import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { watchWorkbenchSnapshots } from '../services/api'
import type { WorkbenchSnapshot } from '../services/api'
import { useAuth } from './AuthContext'
import { mergeWorkbenchSnapshot } from '../utils/workbench'

type WorkbenchState = { snapshot: WorkbenchSnapshot | null; error: string; retry: () => void }
const WorkbenchContext = createContext<WorkbenchState>({ snapshot: null, error: '', retry: () => {} })

export function WorkbenchProvider({ sessionId, taskId, runId, children }: { sessionId: string | null; taskId?: string | null; runId?: string | null; children: ReactNode }) {
  const { user } = useAuth()
  const [value, setValue] = useState<{ scope: string; snapshot: WorkbenchSnapshot | null; error: string }>({ scope: '', snapshot: null, error: '' })
  const [attempt, setAttempt] = useState(0)
  const scope = `${user?.user_id || ''}:${sessionId || ''}:${taskId || ''}:${runId || ''}`
  const retry = useCallback(() => setAttempt((current) => current + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    if (!user) return () => controller.abort()
    void (async () => {
      try {
        for await (const snapshot of watchWorkbenchSnapshots(sessionId, taskId, runId, controller.signal)) {
          if (!controller.signal.aborted) setValue((previous) => ({ scope, snapshot: mergeWorkbenchSnapshot(previous.scope === scope ? previous.snapshot : null, snapshot), error: '' }))
        }
      } catch (cause) {
        if (!controller.signal.aborted) setValue((previous) => ({ scope, snapshot: previous.scope === scope ? previous.snapshot : null, error: cause instanceof Error ? cause.message : String(cause) }))
      }
    })()
    return () => controller.abort()
  }, [scope, sessionId, taskId, runId, user?.user_id, attempt])

  return <WorkbenchContext.Provider value={{ snapshot: value.scope === scope ? value.snapshot : null, error: value.scope === scope ? value.error : '', retry }}>{children}</WorkbenchContext.Provider>
}

export function useWorkbench() {
  return useContext(WorkbenchContext)
}
