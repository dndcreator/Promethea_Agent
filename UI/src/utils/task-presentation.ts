export function taskStatusLabel(status: unknown, fallback: string, t: (zh: string, en: string) => string): string {
  const labels: Record<string, [string, string]> = {
    open: ['待开始', 'Open'],
    pending: ['待执行', 'Pending'],
    running: ['进行中', 'Running'],
    waiting_user: ['等待确认', 'Waiting for review'],
    waiting_human: ['等待确认', 'Waiting for review'],
    retry_wait: ['等待重试', 'Waiting to retry'],
    paused: ['已暂停', 'Paused'],
    completed: ['已完成', 'Completed'],
    succeeded: ['已完成', 'Completed'],
    success: ['已完成', 'Completed'],
    done: ['已完成', 'Completed'],
    failed: ['失败', 'Failed'],
    cancelled: ['已停止', 'Stopped'],
    canceled: ['已停止', 'Stopped'],
    stopped: ['已停止', 'Stopped'],
  }
  const label = labels[String(status || '').toLowerCase()]
  return label ? t(...label) : fallback
}
