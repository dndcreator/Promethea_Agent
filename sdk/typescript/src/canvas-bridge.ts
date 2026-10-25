import type { CanvasEnvironment, CanvasStateWrite, CanvasSemanticSnapshot, SemanticExpression, SemanticUIFeedback } from './generated/public-contracts.js'
import type { CanvasClient } from './canvas.js'
import type { SemanticUIClient } from './semantic-ui.js'

export type CanvasFrameOptions = {
  semanticUI?: SemanticUIClient
  onAttention?: (attention: { component_id: string; definition_revision: string } | null) => void
  labels?: { dismiss: string; retry: string }
}

/** Connect one opaque iframe to its own state, never to arbitrary Runtime methods. */
export function connectCanvasFrame(frame: HTMLIFrameElement, client: CanvasClient, environment: CanvasEnvironment, options: CanvasFrameOptions = {}): () => void {
  const channel = new MessageChannel()
  let active = true
  let inFlight = 0
  let reports = 0
  let watcher: ReturnType<typeof setInterval> | undefined
  let latestRevision = -1
  let polling = false
  let presentationWatcher: ReturnType<typeof setInterval> | undefined
  let presenting = false
  let semantics: CanvasSemanticSnapshot | undefined
  let expressions: SemanticExpression[] = []
  const belongs = (item: SemanticExpression) => item.canvas_anchor?.resource.id === environment.environment_id
    && item.canvas_anchor.resource.kind === 'canvas'
    && item.canvas_anchor.resource.workspace_id === environment.workspace_id
    && item.canvas_anchor.definition_revision === semantics?.definition_revision
    && semantics?.components?.some((node) => node.component_id === item.canvas_anchor?.component_id)
    && !item.hidden && item.state !== 'dismissed'
  const publish = () => {
    if (active) channel.port1.postMessage({ event: 'semantic.changed', semantics, expressions, labels: options.labels })
  }
  const refreshPresentation = async () => {
    if (!active || presenting || document.visibilityState === 'hidden' || !options.semanticUI) return
    presenting = true
    try {
      const [current, state] = await Promise.all([client.semantics(environment), options.semanticUI.get()])
      if (!active) return
      semantics = current
      expressions = (state.expressions || []).map((item) => {
        const previous = expressions.find((row) => row.expression_id === item.expression_id)
        return previous && previous.revision > item.revision ? previous : item
      }).filter(belongs)
      publish()
    } catch {
      // Never keep presenting an unvalidated anchor after its source becomes unavailable.
      semantics = undefined; expressions = []; publish()
    } finally { presenting = false }
  }
  channel.port1.onmessage = async ({ data }: MessageEvent) => {
    if (!active || typeof data?.id !== 'string' || data.id.length > 80 || inFlight >= 32) return
    inFlight += 1
    try {
      if (JSON.stringify(data).length > 256000) throw new Error('Canvas request is too large')
      let result: unknown
      if (data.method === 'state.get') result = await client.getState(environment)
      else if (data.method === 'state.watch') {
        result = await client.getState(environment)
        latestRevision = result && typeof result === 'object' && 'revision' in result ? Number(result.revision) : -1
        if (!watcher) watcher = setInterval(() => {
          if (!active || polling || document.visibilityState === 'hidden') return
          polling = true
          void client.getState(environment).then((state) => {
            if (active && Number(state.revision || 0) > latestRevision) {
              latestRevision = Number(state.revision || 0)
              channel.port1.postMessage({ event: 'state.changed', state })
            }
          }).catch(() => {}).finally(() => { polling = false })
        }, 1500)
      }
      else if (data.method === 'state.set') {
        const params = data.params as CanvasStateWrite
        if (!Number.isInteger(params.expected_revision) || !params.value || typeof params.value !== 'object' || Array.isArray(params.value)) throw new Error('Invalid canvas state')
        result = await client.setState(environment, params)
      } else if (data.method === 'attention.report') {
        const id = data.params?.component_id
        if (document.activeElement !== frame) throw new Error('Canvas is not focused')
        if (id != null && (!semantics || !semantics.components?.some((node) => node.component_id === id))) throw new Error('Unknown Canvas component')
        options.onAttention?.(id == null ? null : { component_id: id, definition_revision: semantics!.definition_revision })
        result = { ok: true }
      } else if (data.method === 'semantic.feedback' && options.semanticUI) {
        const item = expressions.find((row) => row.expression_id === data.params?.expression_id && belongs(row))
        if (!item) throw new Error('Expression does not belong to this Canvas')
        const command = data.params?.command as SemanticUIFeedback
        if (!command || command.expected_revision !== item.revision) throw new Error('Expression changed')
        result = await options.semanticUI.feedback(item.expression_id, command)
        if (active) { expressions = expressions.map((row) => row.expression_id === item.expression_id ? result as SemanticExpression : row).filter(belongs); publish() }
      } else if (data.method === 'diagnostic.report' && reports++ < 10) {
        result = await client.reportError(environment, String(data.params?.message || ''))
      } else throw new Error('Unsupported canvas request')
      if (active) channel.port1.postMessage({ id: data.id, result })
    } catch (error) {
      if (active) channel.port1.postMessage({ id: data.id, error: error instanceof Error ? error.message : String(error) })
    } finally {
      inFlight -= 1
    }
  }
  channel.port1.start()
  frame.contentWindow?.postMessage({ type: 'promethea:connect', version: 1 }, '*', [channel.port2])
  if (options.semanticUI) {
    void refreshPresentation()
    presentationWatcher = setInterval(() => { void refreshPresentation() }, 1500)
  }
  return () => { active = false; if (watcher) clearInterval(watcher); if (presentationWatcher) clearInterval(presentationWatcher); channel.port1.close() }
}
