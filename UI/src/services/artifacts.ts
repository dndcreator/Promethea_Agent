import { getWorkbenchArtifact } from './api'

// Never navigate a same-origin Blob tab to active, tool-produced HTML/SVG.
const PREVIEW_TYPES = new Set(['application/pdf', 'text/plain', 'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif'])

export async function openWorkbenchArtifact(workspaceId: string, path: string, label?: string): Promise<void> {
  const preview = window.open('about:blank', '_blank')
  if (preview) preview.opener = null
  try {
    const blob = await getWorkbenchArtifact(workspaceId, path)
    const url = URL.createObjectURL(blob)
    try {
      if (preview && PREVIEW_TYPES.has(blob.type.split(';')[0].toLowerCase())) preview.location.replace(url)
      else {
        preview?.close()
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = label || path.split(/[\\/]/).pop() || 'artifact'
        anchor.click()
      }
    } finally {
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    }
  } catch (error) {
    preview?.close()
    throw error
  }
}
