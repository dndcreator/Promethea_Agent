import type { Attachment, FileUploadResponse, UserFile } from './generated/public-contracts.js'
import { HttpTransport } from './transport/http.js'

export interface FileUploadOptions {
  sessionId?: string
  filename?: string
}

export class FilesClient {
  constructor(private readonly transport: HttpTransport) {}

  async upload(file: Blob, options: FileUploadOptions = {}, signal?: AbortSignal): Promise<UserFile> {
    const form = new FormData()
    form.append('file', file, options.filename)
    if (options.sessionId) form.append('session_id', options.sessionId)
    const response = await this.transport.send('/api/files/upload', {
      method: 'POST',
      body: form,
      signal,
    })
    const payload = await response.json() as FileUploadResponse
    return payload.file
  }

  attachment(file: UserFile): Attachment {
    return {
      file_id: file.file_id,
      filename: file.filename,
      modality: file.modality,
      content_type: file.content_type,
      size: file.bytes,
      text_extraction_status: file.text_extraction_status,
    }
  }
}
