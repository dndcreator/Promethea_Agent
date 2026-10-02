import type { Error as ErrorDetail } from './generated/public-contracts.js'

type JsonObject = Record<string, unknown>

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function detailFromPayload(payload: unknown): JsonObject {
  if (!isObject(payload)) return {}
  if (isObject(payload.error_detail)) return payload.error_detail
  if (isObject(payload.error)) return payload.error
  if (isObject(payload.detail)) return payload.detail
  if (isObject(payload.payload) && isObject(payload.payload.error_detail)) {
    return payload.payload.error_detail
  }
  return {}
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

export class PrometheaError extends globalThis.Error {
  readonly code: string
  readonly retryable: boolean
  readonly traceId?: string
  readonly dependency?: string
  readonly advice?: string
  readonly status?: number
  readonly detail: ErrorDetail

  constructor(detail: ErrorDetail, status?: number) {
    super(detail.message)
    this.name = 'PrometheaError'
    this.code = detail.code
    this.retryable = Boolean(detail.retryable)
    this.traceId = detail.trace_id ?? undefined
    this.dependency = detail.dependency ?? undefined
    this.advice = detail.advice ?? undefined
    this.status = status
    this.detail = detail
  }
}

export function errorFromPayload(
  payload: unknown,
  options: { status?: number; fallback?: string } = {},
): PrometheaError {
  const root = isObject(payload) ? payload : {}
  const detail = detailFromPayload(payload)
  const message =
    text(detail.message) ??
    text(root.error) ??
    text(root.detail) ??
    text(root.message) ??
    text(root.content) ??
    options.fallback ??
    'Promethea request failed'
  const code = text(detail.code) ?? `http_${options.status ?? 'error'}`
  return new PrometheaError(
    {
      ...detail,
      code,
      message,
      retryable: Boolean(detail.retryable),
    } as ErrorDetail,
    options.status,
  )
}

export async function errorFromResponse(response: Response): Promise<PrometheaError> {
  const raw = await response.text()
  let payload: unknown = raw
  if (raw) {
    try {
      payload = JSON.parse(raw)
    } catch {
      payload = raw
    }
  }
  return errorFromPayload(payload, {
    status: response.status,
    fallback: response.statusText || `HTTP ${response.status}`,
  })
}
