import type { WorkbenchSnapshot } from '../services/api'

export function mergeWorkbenchSnapshot(previous: WorkbenchSnapshot | null, incoming: WorkbenchSnapshot): WorkbenchSnapshot {
  const key = (snapshot: WorkbenchSnapshot) => {
    const scope = snapshot.scope
    return [scope.user_id, scope.session_id, scope.task_id, scope.run_id].join(':')
  }
  if (!previous || key(previous) !== key(incoming)) return incoming
  const timeline = new Map((previous.timeline || []).map((item) => [item.activity_id, item]))
  for (const item of incoming.timeline || []) {
    const existing = timeline.get(item.activity_id)
    timeline.set(item.activity_id, { ...existing, ...item, detail: { ...existing?.detail, ...item.detail } })
  }
  return { ...incoming, timeline: [...timeline.values()].sort((a, b) => Number(a.seq || 0) - Number(b.seq || 0)).slice(-160) }
}
