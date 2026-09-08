import type { AssistantHistoryMessage } from './types'

type HistorySource = {
  id: string
  role: 'assistant' | 'user'
  text?: string
  error?: string | null
}

export function buildAssistantHistory(messages: HistorySource[]): AssistantHistoryMessage[] {
  let usedChars = 0
  return messages
    .filter(item => item.id !== 'welcome' && !item.error && item.text)
    .slice(-8)
    .map<AssistantHistoryMessage>(item => ({ role: item.role, content: item.text!.slice(0, 2000) }))
    .filter(item => {
      if (usedChars + item.content.length > 8000) return false
      usedChars += item.content.length
      return true
    })
}
