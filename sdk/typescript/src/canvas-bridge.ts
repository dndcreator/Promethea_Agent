import type { CanvasEnvironment, CanvasStateWrite } from './generated/public-contracts.js'
import type { CanvasClient } from './canvas.js'

/** Connect one opaque iframe to its own state, never to arbitrary Runtime methods. */
export function connectCanvasFrame(frame: HTMLIFrameElement, client: CanvasClient, environment: CanvasEnvironment): () => void {
  const channel = new MessageChannel()
  let active = true
  let inFlight = 0
  let reports = 0
  channel.port1.onmessage = async ({ data }: MessageEvent) => {
    if (!active || typeof data?.id !== 'string' || data.id.length > 80 || inFlight >= 32) return
    inFlight += 1
    try {
      if (JSON.stringify(data).length > 256000) throw new Error('Canvas request is too large')
      let result: unknown
      if (data.method === 'state.get') result = await client.getState(environment)
      else if (data.method === 'state.set') {
        const params = data.params as CanvasStateWrite
        if (!Number.isInteger(params.expected_revision) || !params.value || typeof params.value !== 'object' || Array.isArray(params.value)) throw new Error('Invalid canvas state')
        result = await client.setState(environment, params)
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
  return () => { active = false; channel.port1.close() }
}
