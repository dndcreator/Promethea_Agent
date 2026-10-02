import { errorFromResponse } from '../errors.js'

export type TokenProvider = () => string | undefined | Promise<string | undefined>

export interface HttpTransportOptions {
  baseUrl: string
  token?: string | TokenProvider
  fetch?: typeof globalThis.fetch
  credentials?: RequestCredentials
}

export class HttpTransport {
  private readonly baseUrl: string
  private readonly token?: string | TokenProvider
  private readonly fetchImpl: typeof globalThis.fetch
  private readonly credentials?: RequestCredentials

  constructor(options: HttpTransportOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.token = options.token
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis)
    this.credentials = options.credentials
  }

  private async authToken(): Promise<string | undefined> {
    return typeof this.token === 'function' ? this.token() : this.token
  }

  async request(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers)
    const token = await this.authToken()
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`)
    }
    const url = /^https?:\/\//i.test(path)
      ? path
      : `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`
    return await this.fetchImpl(url, {
      ...init,
      headers,
      credentials: init.credentials ?? this.credentials,
    })
  }

  async send(path: string, init: RequestInit = {}): Promise<Response> {
    const response = await this.request(path, init)
    if (!response.ok) throw await errorFromResponse(response)
    return response
  }

  async json<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers)
    if (init.body !== undefined && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
    const response = await this.send(path, { ...init, headers })
    return await response.json() as T
  }
}
