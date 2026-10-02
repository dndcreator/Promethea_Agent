export interface SseMessage {
  event?: string
  id?: string
  data: string
}

function parseBlock(block: string): SseMessage | undefined {
  let event: string | undefined
  let id: string | undefined
  const data: string[] = []
  for (const rawLine of block.split('\n')) {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
    if (!line || line.startsWith(':')) continue
    const separator = line.indexOf(':')
    const field = separator < 0 ? line : line.slice(0, separator)
    let value = separator < 0 ? '' : line.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    if (field === 'id') id = value
    if (field === 'data') data.push(value)
  }
  if (data.length === 0) return undefined
  return { event, id, data: data.join('\n') }
}

export async function* parseSse(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<SseMessage> {
  if (!response.body) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      if (signal?.aborted) throw signal.reason ?? new DOMException('Aborted', 'AbortError')
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const message = parseBlock(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        if (message) yield message
        boundary = buffer.indexOf('\n\n')
      }
      if (done) break
    }
    const finalMessage = parseBlock(buffer)
    if (finalMessage) yield finalMessage
  } finally {
    if (signal?.aborted) await reader.cancel(signal.reason).catch(() => undefined)
    reader.releaseLock()
  }
}
