import type { ChannelAccount, ChannelDelivery, ChannelPairing, ChannelPairingRequest } from './generated/public-contracts.js'
import type { HttpTransport } from './transport/http.js'

export class ChannelsClient {
  constructor(private readonly transport: HttpTransport) {}

  list(signal?: AbortSignal): Promise<ChannelAccount[]> {
    return this.transport.json('/api/channels', { signal })
  }

  pair(command: ChannelPairingRequest, signal?: AbortSignal): Promise<ChannelPairing> {
    return this.transport.json('/api/channels/pairings', { method: 'POST', body: JSON.stringify(command), signal })
  }

  unbind(channel: string, signal?: AbortSignal): Promise<{ ok: boolean }> {
    return this.transport.json(`/api/channels/${encodeURIComponent(channel)}/binding`, { method: 'DELETE', signal })
  }

  deliveries(signal?: AbortSignal): Promise<ChannelDelivery[]> {
    return this.transport.json('/api/channels/deliveries', { signal })
  }

  retry(deliveryId: string, signal?: AbortSignal): Promise<{ ok: boolean }> {
    return this.transport.json(`/api/channels/deliveries/${encodeURIComponent(deliveryId)}/retry`, { method: 'POST', signal })
  }
}
