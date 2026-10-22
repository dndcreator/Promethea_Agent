export interface MessageData {
  id: string
  role: 'user' | 'agent' | 'assistant' | 'tool' | 'status'
  content: string
  name?: string
  time?: string
  reasoningTreeId?: string
  conversationTurnId?: string
  reasoningSteps?: ReasoningStep[]
  runStatus?: string
  error?: Record<string, unknown>
}

export type ReasoningStep = {
  step_id: string
  source: string
  content: string
}

export type FollowupData = {
  id: string
  message_id: string
  selected_text: string
  start_offset: number
  end_offset: number
  query_type: string
  custom_query?: string | null
  query: string
  response: string
  created_at: number
}

export type TextSelection = {
  messageId: string
  selectedText: string
  startOffset: number
  endOffset: number
  left: number
  top: number
}
