import type { VoiceCapabilities, VoiceDiscoveryRequest, VoiceModelList, VoiceTranscription, VoiceTTSRequest } from './generated/public-contracts.js'
import type { HttpTransport } from './transport/http.js'

export class VoiceClient {
  constructor(private readonly transport: HttpTransport) {}

  status(signal?: AbortSignal): Promise<VoiceCapabilities> {
    return this.transport.json('/api/voice/status', { signal })
  }

  models(request: VoiceDiscoveryRequest, signal?: AbortSignal): Promise<VoiceModelList> {
    return this.transport.json('/api/voice/models', { method: 'POST', body: JSON.stringify(request), signal })
  }

  async synthesize(request: VoiceTTSRequest, signal?: AbortSignal): Promise<Blob> {
    return (await this.transport.send('/api/voice/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request), signal })).blob()
  }

  transcribe(audio: Blob, filename: string, signal?: AbortSignal): Promise<VoiceTranscription> {
    const body = new FormData()
    body.append('audio', audio, filename)
    return this.transport.json('/api/voice/stt', { method: 'POST', body, signal })
  }
}
