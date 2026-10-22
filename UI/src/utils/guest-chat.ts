import type { GuestChatMessage, GuestChatStatus } from '@promethea/sdk'

type Message = { role: string; content: string; error?: unknown }

export function guestTranscript(messages: Message[], input: string, limits: GuestChatStatus): GuestChatMessage[] {
  const history: GuestChatMessage[] = []
  let pending: Message | undefined
  for (const message of messages) {
    if (message.role === 'user') pending = message
    else if (pending && ['agent', 'assistant'].includes(message.role) && message.content && !message.error) {
      history.push({ role: 'user', content: pending.content }, { role: 'assistant', content: message.content })
      pending = undefined
    }
  }
  history.push({ role: 'user', content: input })
  while (history.length > 1 && (history.length > limits.max_messages || history.reduce((sum, message) => sum + message.content.length, 0) > limits.max_input_chars)) {
    history.splice(0, 2)
  }
  return history
}
