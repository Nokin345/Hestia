export interface RetrievedMemory {
  id: string
  text: string
  category: string
  type: 'pinned' | 'recalled'
}

export interface KbSource {
  filename: string
  similarity: number
}

export type ChatEventData =
  | { event: 'conversation'; data: { conversation_id: string } }
  | { event: 'delta'; data: { content: string } }
  | { event: 'reasoning'; data: { content: string } }
  | { event: 'memory_retrieved'; data: { count: number; memories?: RetrievedMemory[] } }
  | { event: 'kb_retrieved'; data: { count: number; sources?: KbSource[] } }
  | { event: 'tool_call'; data: { id: string; name: string; arguments: Record<string, unknown> } }
  | { event: 'tool_result'; data: { name: string; ok: boolean; summary: string } }
  | { event: 'tool'; data: { name: string; ok: boolean; arguments: Record<string, unknown>; content: string } }
  | { event: 'done'; data: { message_id: string; conversation_id?: string; usage?: unknown } }
  | { event: 'error'; data: { message: string } }

export interface StreamChatBody {
  conversation_id?: string | null
  provider?: string | null
  model?: string | null
  skill_id?: string | null
  content: string
  parts?: unknown[]
  reasoning?: boolean | null
  search?: boolean
  code?: boolean
  mcp_tools?: string[]
  kb?: boolean
  memory?: boolean
  system_prompt?: string | null
  temperature?: number | null
}

export async function streamChat(
  body: StreamChatBody,
  onEvent: (e: ChatEventData) => void,
  signal: AbortSignal,
  path = '/api/chat',
): Promise<void> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    credentials: 'include',
    signal,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 300)}`)
  }
  if (!res.body) throw new Error('No response body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const parse = (raw: string) => {
    const eventMatch = raw.match(/^event: (.+)$/m)
    const dataMatch = raw.match(/^data: (.+)$/m)
    if (!dataMatch) return
    const event = eventMatch ? eventMatch[1] : 'message'
    let data: Record<string, unknown>
    try {
      data = JSON.parse(dataMatch[1])
    } catch {
      return
    }
    onEvent({ event, data } as ChatEventData)
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n|\r/g, '\n')
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      if (raw.trim()) parse(raw)
    }
  }
}
