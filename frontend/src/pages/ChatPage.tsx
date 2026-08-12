import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Send, Square, Sparkles, Brain, Globe, Terminal, X, FileText, AlertTriangle } from 'lucide-react'
import { apiFetch, apiPatch, apiDelete, apiUpload } from '../api/client'
import { streamChat } from '../api/stream'
import { readLastModels, writeLastModels } from '../persist'
import type { ChatEventData, KbSource, RetrievedMemory } from '../api/stream'
import type { ChatUsage, Conversation, DefaultsConfig, McpToolDef, Message, ModelEntry, SystemPromptPreset } from '../api/types'
import { Layout } from '../components/layout/Layout'
import { AssistantTurn, EditBox, MessageBubble } from '../components/chat/Message'
import { ComposerMenu } from '../components/chat/ComposerMenu'
import ModelSelector from '../components/chat/ModelSelector'
import { Button } from '../components/ui'
import { useAuth } from '../store/auth'

interface ActiveMessage extends Message {
  temp: boolean
  retrievedMemories?: RetrievedMemory[]
  retrievedKb?: KbSource[]
}

type Attachment = { url: string; mime: string; name?: string; text?: string }

function attachmentParts(attachments: Attachment[]): { type: string; text?: string; image_url?: string; image_mime?: string }[] {
  const parts: { type: string; text?: string; image_url?: string; image_mime?: string }[] = []
  for (const a of attachments) {
    if (a.mime.startsWith('image/')) {
      parts.push({ type: 'image_url', image_url: a.url, image_mime: a.mime })
    } else if (a.text) {
      parts.push({ type: 'text', text: `[Attachment: ${a.name ?? a.url}]\n${a.text}` })
    }
  }
  return parts
}

const MODEL_KEY_SEP = '::'

function parseModelKey(key: string): { provider: string; model: string } {
  const idx = key.indexOf(MODEL_KEY_SEP)
  if (idx === -1) return { provider: '', model: key }
  return { provider: key.slice(0, idx), model: key.slice(idx + MODEL_KEY_SEP.length) }
}

export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const conversationId = searchParams.get('c')
  const username = useAuth((s) => s.username)

  const [messages, setMessages] = useState<ActiveMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [activeTool, setActiveTool] = useState<string | null>(null)
  const [modelKey, setModelKey] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingText, setEditingText] = useState('')
  const [reasoning, setReasoning] = useState<boolean>(true)
  const [searchEnabled, setSearchEnabled] = useState<boolean>(false)
  const [codeEnabled, setCodeEnabled] = useState<boolean>(false)
  const [mcpTools, setMcpTools] = useState<string[]>([])
  const [kbEnabled, setKbEnabled] = useState<boolean>(false)
  const [memoryEnabled, setMemoryEnabled] = useState<boolean>(false)
  const [modelSwitchedFrom, setModelSwitchedFrom] = useState<string | null>(null)
  const [systemPrompt, setSystemPrompt] = useState<string>('')
  const [temperature, setTemperature] = useState<number>(0.7)
  const [attachments, setAttachments] = useState<
    { url: string; mime: string; name?: string; text?: string }[]
  >([])
  const [attaching, setAttaching] = useState(false)
  const attachInputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [savedNotice, setSavedNotice] = useState<string | null>(null)
  const savedNoticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const flashSavedNotice = useCallback((text: string) => {
    setSavedNotice(text)
    if (savedNoticeTimerRef.current) clearTimeout(savedNoticeTimerRef.current)
    savedNoticeTimerRef.current = setTimeout(() => setSavedNotice(null), 3500)
  }, [])
  // Keep the most recent retrieved-memory set in a ref so it can be reattached
  // to the assistant message after a conversation reload (e.g. the first-message
  // URL change to ?c=...) without losing the pill.
  const retrievedStoreRef = useRef<Record<string, RetrievedMemory[]>>({})
  const kbStoreRef = useRef<Record<string, KbSource[]>>({})
  const reattachRetrieved = useCallback(
    (list: Message[]): ActiveMessage[] => {
      const store = retrievedStoreRef.current
      const kbs = kbStoreRef.current
      const merged = list.map((m) => {
        const active = { ...m, temp: false } as ActiveMessage
        // Prefer the persisted server snapshot (survives reload).
        if (m.memories_used && m.memories_used.length) {
          active.retrievedMemories = m.memories_used
        } else if (m.role === 'assistant' && store[m.id]) {
          active.retrievedMemories = store[m.id]
        }
        if (m.role === 'assistant' && kbs[m.id]) {
          active.retrievedKb = kbs[m.id]
        }
        return active
      })
      if (Object.keys(store).length > 0) {
        const entries = Object.entries(store)
        const [, latest] = entries[entries.length - 1]
        const hasAny = merged.some((m) => m.retrievedMemories?.length)
        if (!hasAny) {
          for (let i = merged.length - 1; i >= 0; i--) {
            if (merged[i].role === 'assistant') {
              merged[i].retrievedMemories = latest as RetrievedMemory[]
              break
            }
          }
        }
      }
      if (Object.keys(kbs).length > 0) {
        const entries = Object.entries(kbs)
        const [, latest] = entries[entries.length - 1]
        const hasAny = merged.some((m) => m.retrievedKb?.length)
        if (!hasAny) {
          for (let i = merged.length - 1; i >= 0; i--) {
            if (merged[i].role === 'assistant') {
              merged[i].retrievedKb = latest as KbSource[]
              break
            }
          }
        }
      }
      return merged
    },
    [],
  )

  const { data: modelEntries, isPending: modelsPending } = useQuery({
    queryKey: ['models'],
    queryFn: () => apiFetch<ModelEntry[]>('/providers/models'),
    refetchOnWindowFocus: true,
  })

  const { data: defaults } = useQuery({
    queryKey: ['defaults'],
    queryFn: () => apiFetch<DefaultsConfig>('/defaults'),
  })

  const { data: presets } = useQuery({
    queryKey: ['presets'],
    queryFn: () => apiFetch<SystemPromptPreset[]>('/defaults/presets'),
  })

  const { data: allMcpTools } = useQuery({
    queryKey: ['mcp-all-tools'],
    queryFn: () => apiFetch<McpToolDef[]>('/mcp/tools'),
  })

  // Remember the last working models so the dropdown is populated instantly on
  // load, even before the async reachability/refetch settles.
  useEffect(() => {
    if (modelEntries?.length) writeLastModels(modelEntries)
  }, [modelEntries])

  const knownModels = useMemo<ModelEntry[]>(() => {
    if (modelEntries?.length) return modelEntries
    return readLastModels<ModelEntry>()
  }, [modelEntries])

  const groups = useMemo(() => {
    const map = new Map<string, ModelEntry[]>()
    for (const entry of knownModels) {
      const list = map.get(entry.provider_id) ?? []
      list.push(entry)
      map.set(entry.provider_id, list)
    }
    return Array.from(map.entries()).map(([providerId, models]) => ({
      providerId,
      providerName: models[0]?.provider_name ?? providerId,
      models,
    }))
  }, [knownModels])

  const hasModels = knownModels.length > 0
  // Only surface the "no models" warning once loading has fully settled and
  // the reachability check came back empty. Avoids flashing it on reload while
  // cached models are still being displayed/revalidated.
  const modelsSettled = !modelsPending
  const showNoModelsNotice = modelsSettled && !hasModels

  useEffect(() => {
    if (!knownModels.length) {
      setModelKey('')
      return
    }
    const defaultKey = defaults?.default_model
    const defaultValid =
      defaultKey && knownModels.some((m) => `${m.provider_id}::${m.id}` === defaultKey)
    if (defaultValid) {
      setModelKey(defaultKey!)
      return
    }
    const saved = localStorage.getItem('hestia:lastModel')
    const valid = saved && knownModels.some((m) => `${m.provider_id}::${m.id}` === saved)
    setModelKey(valid ? saved! : `${knownModels[0].provider_id}::${knownModels[0].id}`)
  }, [knownModels, defaults])

  useEffect(() => {
    if (modelKey) localStorage.setItem('hestia:lastModel', modelKey)
  }, [modelKey])

  // Per-conversation settings: loaded from the conversation (if it exists).
  // New chats get the configured defaults — every toggle off except thinking,
  // temperature 0.7, and the system prompt falls back to the "default" preset
  // unless a custom default is set. The conversation persists them henceforth.
  useEffect(() => {
    if (!conversationId) {
      setKbEnabled(defaults?.default_kb_enabled ?? false)
      setMemoryEnabled(defaults?.default_memory_enabled ?? false)
      setReasoning(true)
      setSearchEnabled(defaults?.default_search_enabled ?? false)
      setCodeEnabled(defaults?.default_code_enabled ?? false)
      setMcpTools((allMcpTools ?? []).map((t) => t.name))
      setSystemPrompt(
        defaults?.default_system_prompt?.trim() ||
          presets?.find((p) => p.name === 'default')?.content ||
          '',
      )
      setTemperature(0.7)
      return
    }
    let cancelled = false
    apiFetch<Conversation>(`/conversations/${conversationId}`)
      .then((c) => {
        if (!cancelled) {
          setKbEnabled(!!c.kb_enabled)
          setMemoryEnabled(!!c.memory_enabled)
          setReasoning(c.reasoning_enabled !== false)
          setSearchEnabled(!!c.search_enabled)
          setCodeEnabled(!!c.code_enabled)
          setMcpTools(c.mcp_tools ?? [])
          setSystemPrompt(c.system_prompt ?? '')
          setTemperature(c.temperature != null ? c.temperature : 0.7)
          // If the conversation's model is still known/reachable, restore it.
          // Otherwise it gracefully falls back to the current (global default)
          // selection — just notify the user that the model was swapped out.
          if (c.provider && c.model) {
            const convKey = `${c.provider}::${c.model}`
            if (knownModels.some((m) => `${m.provider_id}::${m.id}` === convKey)) {
              setModelKey(convKey)
              setModelSwitchedFrom(null)
            } else if (knownModels.length > 0) {
              setModelSwitchedFrom(`${c.provider}: ${c.model}`)
            }
          }
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [conversationId, knownModels, defaults, presets, allMcpTools])

  const toggleKb = useCallback(() => {
    const next = !kbEnabled
    setKbEnabled(next)
    if (!conversationId) return
    apiPatch(`/conversations/${conversationId}`, { kb_enabled: next }).catch(() => {})
  }, [kbEnabled, conversationId])

  const toggleMemory = useCallback(() => {
    const next = !memoryEnabled
    setMemoryEnabled(next)
    if (!conversationId) return
    apiPatch(`/conversations/${conversationId}`, { memory_enabled: next }).catch(() => {})
  }, [memoryEnabled, conversationId])

  const toggleMcpTool = useCallback(
    (toolName: string) => {
      const next = mcpTools.includes(toolName)
        ? mcpTools.filter((n) => n !== toolName)
        : [...mcpTools, toolName]
      setMcpTools(next)
      if (!conversationId) return
      apiPatch(`/conversations/${conversationId}`, { mcp_tools: next }).catch(() => {})
    },
    [mcpTools, conversationId],
  )

  const handleModelChange = useCallback(
    (key: string) => {
      setModelKey(key)
      setModelSwitchedFrom(null)
      if (!conversationId) return
      const parsed = parseModelKey(key)
      apiPatch(`/conversations/${conversationId}`, {
        provider: parsed.provider,
        model: parsed.model,
      }).catch(() => {})
    },
    [conversationId],
  )

  // Persist the prompt and temperature to the current conversation as they
  // change, like the toggles, so reopening the chat restores them.
  useEffect(() => {
    if (!conversationId) return
    apiPatch(`/conversations/${conversationId}`, { system_prompt: systemPrompt }).catch(() => {})
  }, [systemPrompt, conversationId])

  useEffect(() => {
    if (!conversationId) return
    apiPatch(`/conversations/${conversationId}`, { temperature }).catch(() => {})
  }, [temperature, conversationId])

  const { provider, model } = useMemo(() => parseModelKey(modelKey), [modelKey])

  const { data: reasoningCap, isLoading: reasoningLoading } = useQuery({
    queryKey: ['reasoning', provider, model],
    queryFn: async () => {
      if (!provider || !model) return null
      const res = await apiFetch<{ reasoning: boolean | null }>(
        `/providers/${provider}/reasoning?model=${encodeURIComponent(model)}`,
      )
      return res.reasoning
    },
    enabled: Boolean(provider && model),
  })

  const showReasoningToggle =
    provider && model && !reasoningLoading && (reasoningCap === true || reasoningCap === null)

  useEffect(() => {
    if (reasoningCap === false) setReasoning(false)
  }, [reasoningCap])

  useEffect(() => {
    let cancelled = false
    setMessages([])
    if (!conversationId) return
    apiFetch<Message[]>(`/conversations/${conversationId}/messages`)
      .then((list) => {
        if (!cancelled) setMessages(reattachRetrieved(list))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [conversationId, reattachRetrieved])

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    const convId = searchParams.get('c') || realConvIdRef.current
    if (!convId) return
    // Land the user on the real conversation so they can edit/regenerate. For a
    // brand-new chat this is where `?c=` finally appears (not during streaming).
    if (searchParams.get('c') !== convId) {
      setSearchParams({ c: convId }, { replace: true })
    }
    // The backend saved the user message at request start; this refetch swaps
    // the temp bubbles for the stored history (dismissing the partial answer).
    window.setTimeout(() => {
      apiFetch<Message[]>(`/conversations/${convId}/messages`)
        .then((list) => setMessages(reattachRetrieved(list)))
        .catch(() => {})
    }, 500)
  }, [searchParams, setSearchParams, reattachRetrieved])

  const aiIdRef = useRef<string | null>(null)
  // The backend assigns the real conversation id up front (SSE `conversation`
  // event). We keep it in a ref instead of changing `?c=` mid-stream: flipping
  // `conversationId` while streaming would re-run the message-load effect and
  // wipe the in-flight temp bubbles. The URL is only (re)applied on stop/done.
  const realConvIdRef = useRef<string | null>(null)
  useEffect(() => {
    realConvIdRef.current = searchParams.get('c')
  }, [searchParams])

  // Streamed reasoning/text needs a home. If the current assistant placeholder
  // is still the last row, patch it in place; otherwise (e.g. it sits before
  // a tool row from the previous round) spawn a fresh assistant row after the
  // tools — this is what keeps each tool round a contiguous run of tool rows.
  const upsertAssistant = useCallback(
    (apply: (m: ActiveMessage) => ActiveMessage) => {
      setMessages((prev) => {
        const id = aiIdRef.current
        const idx = id ? prev.findIndex((m) => m.id === id) : -1
        if (idx !== -1 && idx === prev.length - 1) {
          return prev.map((m, i) => (i === idx ? apply(m) : m))
        }
        const newId = `tmp-ai-${Date.now()}`
        aiIdRef.current = newId
        const base: ActiveMessage = {
          id: newId,
          conversation_id: prev[0]?.conversation_id ?? '',
          role: 'assistant',
          parts: [] as ActiveMessage['parts'],
          model: model || undefined,
          created_at: new Date().toISOString(),
          temp: true,
        }
        return [...prev, apply(base)]
      })
    },
    [model],
  )

  const handleStreamEvent = useCallback(
    () => (e: ChatEventData) => {
      const target = () => aiIdRef.current
      if (e.event === 'conversation') {
        const cid = e.data.conversation_id
        if (cid) realConvIdRef.current = cid
      } else if (e.event === 'delta') {
        const content = e.data.content
        upsertAssistant((m) =>
          m.parts.some((p) => p.type === 'text')
            ? {
                ...m,
                parts: m.parts.map((p) =>
                  p.type === 'text' ? { ...p, text: (p.text ?? '') + content } : p,
                ),
              }
            : { ...m, parts: [...m.parts, { type: 'text', text: content }] },
        )
      } else if (e.event === 'reasoning') {
        const content = e.data.content
        upsertAssistant((m) =>
          m.parts.some((p) => p.type === 'reasoning')
            ? {
                ...m,
                parts: m.parts.map((p) =>
                  p.type === 'reasoning' ? { ...p, text: (p.text ?? '') + content } : p,
                ),
              }
            : { ...m, parts: [{ type: 'reasoning', text: content }, ...m.parts] },
        )
      } else if (e.event === 'error') {
        setActiveTool(null)
        const id = target()
        if (!id) return
        setMessages((prev) =>
          prev.map((m) => (m.id === id ? { ...m, error: e.data.message } : m)),
        )
      } else if (e.event === 'memory_retrieved') {
        const id = target()
        if (!id) return
        const memories = e.data.memories ?? []
        retrievedStoreRef.current = { [id]: memories }
        setMessages((prev) =>
          prev.map((m) =>
            m.id === id
              ? { ...m, retrievedMemories: memories.length ? memories : undefined }
              : m,
          ),
        )
      } else if (e.event === 'memory_saved') {
        const n = e.data.count || 1
        flashSavedNotice(`Saved ${n} memor${n === 1 ? 'y' : 'ies'}`)
      } else if (e.event === 'kb_retrieved') {
        const id = target()
        if (!id) return
        const sources = e.data.sources ?? []
        kbStoreRef.current = { [id]: sources }
        setMessages((prev) =>
          prev.map((m) =>
            m.id === id
              ? { ...m, retrievedKb: sources.length ? sources : undefined }
              : m,
          ),
        )
      } else if (e.event === 'tool') {
        setActiveTool(null)
        const argsJson = JSON.stringify(e.data.arguments ?? {})
        const body = JSON.stringify(e.data.content ?? '')
        const block =
          `${e.data.name} | ${e.data.ok ? 'ok' : 'failed'}` +
          `\nA${argsJson.length}\n${argsJson}` +
          `\nC${body.length}\n${body}`
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          // Same round: consecutive tool events (the backend emits them all
          // before the next model turn) append into ONE tool row, keeping the
          // round a single contiguous chain bubble.
          if (last && last.role === 'tool' && last.temp) {
            return prev.map((m, i) =>
              i === prev.length - 1
                ? {
                    ...m,
                    parts: [
                      { type: 'text', text: `${m.parts[0]?.text ?? ''}\n\n${block}` },
                    ],
                  }
                : m,
            )
          }
          return [
            ...prev,
            {
              id: `tmp-tool-${Date.now()}`,
              conversation_id: prev[0]?.conversation_id ?? '',
              role: 'tool',
              parts: [{ type: 'text', text: block }],
              created_at: new Date().toISOString(),
              temp: true,
            } as ActiveMessage,
          ]
        })
      } else if (e.event === 'tool_call') {
        setActiveTool(e.data.name)
      } else if (e.event === 'done') {
        setActiveTool(null)
        const newId = e.data.conversation_id as string | undefined
        const convId = newId || conversationId
        const usage = (e.data as { usage?: unknown }).usage as ChatUsage | undefined
        const msgId = aiIdRef.current
        setMessages((prev) =>
          prev.map((m) => (m.id === msgId ? { ...m, usage: usage ?? null } : m)),
        )
        if (newId && newId !== conversationId) {
          setSearchParams({ c: newId }, { replace: true })
        }
        if (convId) {
          apiFetch<Message[]>(`/conversations/${convId}/messages`)
            .then((list) => setMessages(reattachRetrieved(list)))
            .catch(() => {})
        }
      }
    },
    [conversationId, model, setSearchParams, flashSavedNotice, reattachRetrieved, upsertAssistant],
  )

  const send = useCallback(
    async (text: string) => {
      if ((!text.trim() && attachments.length === 0) || streaming) return
      const content = text.trim()
      const convProvider = provider || ''
      const convModel = model || ''
      setInput('')
      setActiveTool(null)

      const tempUser: ActiveMessage = {
        id: `tmp-user-${Date.now()}`,
        conversation_id: conversationId ?? '',
        role: 'user',
        parts: [
          ...attachmentParts(attachments),
          ...(content ? [{ type: 'text', text: content }] : []),
        ],
        created_at: new Date().toISOString(),
        temp: true,
      }
      const tempAssistant: ActiveMessage = {
        id: `tmp-ai-${Date.now()}`,
        conversation_id: conversationId ?? '',
        role: 'assistant',
        parts: [{ type: 'text', text: '' }],
        model: model || undefined,
        created_at: new Date().toISOString(),
        temp: true,
      }
      setMessages((prev) => [...prev, tempUser, tempAssistant])
      setStreaming(true)
      aiIdRef.current = tempAssistant.id

      const controller = new AbortController()
      abortRef.current = controller

      try {
        await streamChat(
          {
            conversation_id: conversationId ?? null,
            provider: convProvider,
            model: convModel,
            content,
            parts: attachmentParts(attachments),
            reasoning,
            search: searchEnabled,
            code: codeEnabled,
            mcp_tools: mcpTools,
            kb: kbEnabled,
            memory: memoryEnabled,
            system_prompt: systemPrompt || null,
            temperature,
          },
          handleStreamEvent(),
          controller.signal,
        )
        setAttachments([])
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiIdRef.current ? { ...m, error: (err as Error).message } : m,
            ),
          )
        }
      } finally {
        setStreaming(false)
        abortRef.current = null
        queryClient.invalidateQueries({ queryKey: ['conversations'] })
      }
    },
    [conversationId, model, provider, streaming, reasoning, searchEnabled, codeEnabled, mcpTools, kbEnabled, memoryEnabled, systemPrompt, temperature, attachments, queryClient, handleStreamEvent],
  )

  const sendEdit = useCallback(
    async (messageId: string, newText: string) => {
      if (!conversationId || streaming) return
      const content = newText.trim()
      if (!content) return
      setEditingId(null)
      setInput('')

      const tempAssistant: ActiveMessage = {
        id: `tmp-ai-${Date.now()}`,
        conversation_id: conversationId,
        role: 'assistant',
        parts: [{ type: 'text', text: '' }],
        model: model || undefined,
        created_at: new Date().toISOString(),
        temp: true,
      }
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === messageId)
        if (idx === -1) return [...prev, tempAssistant]
        const edited = {
          ...prev[idx],
          parts: [{ type: 'text', text: content }],
        }
        return [...prev.slice(0, idx), edited, tempAssistant]
      })
      setStreaming(true)
      aiIdRef.current = tempAssistant.id

      const controller = new AbortController()
      abortRef.current = controller

      try {
        await streamChat(
          {
            conversation_id: conversationId,
            content,
            reasoning,
            search: searchEnabled,
            code: codeEnabled,
            mcp_tools: mcpTools,
            kb: kbEnabled,
            memory: memoryEnabled,
            system_prompt: systemPrompt || null,
            temperature,
          },
          handleStreamEvent(),
          controller.signal,
          `/api/conversations/${conversationId}/messages/${messageId}/regenerate`,
        )
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiIdRef.current ? { ...m, error: (err as Error).message } : m,
            ),
          )
        }
      } finally {
        setStreaming(false)
        abortRef.current = null
        queryClient.invalidateQueries({ queryKey: ['conversations'] })
      }
    },
    [conversationId, model, streaming, reasoning, searchEnabled, codeEnabled, mcpTools, kbEnabled, systemPrompt, temperature, queryClient, handleStreamEvent],
  )

  const startEditMessage = useCallback(
    (messageId: string) => {
      const m = messages.find((x) => x.id === messageId)
      if (!m) return
      const text = m.parts
        .filter((p) => p.type === 'text')
        .map((p) => p.text ?? '')
        .join('')
      setEditingId(messageId)
      setEditingText(text)
    },
    [messages],
  )

  const saveEdit = useCallback(
    async (messageId: string, newText: string) => {
      if (!conversationId || streaming) return
      const content = newText.trim()
      if (!content) return
      setEditingId(null)
      try {
        await apiPatch(`/conversations/${conversationId}/messages/${messageId}`, { content })
        const list = await apiFetch<Message[]>(`/conversations/${conversationId}/messages`)
        setMessages(list.map((m) => ({ ...m, temp: false })))
      } catch (err) {
        alert((err as Error).message)
      }
    },
    [conversationId, streaming],
  )

  const deleteMessage = useCallback(
    async (messageIds: string[]) => {
      if (!conversationId || streaming) return
      try {
        for (const mid of messageIds) {
          await apiDelete(`/conversations/${conversationId}/messages/${mid}`)
        }
        const list = await apiFetch<Message[]>(`/conversations/${conversationId}/messages`)
        setMessages(list.map((m) => ({ ...m, temp: false })))
        if (editingId && messageIds.includes(editingId)) setEditingId(null)
      } catch (err) {
        alert((err as Error).message)
      }
    },
    [conversationId, streaming, editingId],
  )

  const startNewChat = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()
    setSearchParams({}, { replace: true })
    setMessages([])
    setInput('')
    setEditingId(null)
    setModelSwitchedFrom(null)
    retrievedStoreRef.current = {}
  }, [setSearchParams])

  const handleAttachFiles = useCallback(() => {
    attachInputRef.current?.click()
  }, [])

  const handleAttachChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? [])
      e.target.value = ''
      if (!files.length) return
      setAttaching(true)
      const results: { url: string; mime: string; name?: string; text?: string }[] = []
      try {
        for (const file of files) {
          const res = await apiUpload(file)
          const isText = !res.mime.startsWith('image/')
          let text: string | undefined
          if (isText && file.size <= 1024 * 1024) {
            text = await file.text()
          }
          results.push({ url: res.url, mime: res.mime, name: file.name, text })
        }
        setAttachments((prev) => [...prev, ...results])
      } catch (err) {
        alert((err as Error).message)
      } finally {
        setAttaching(false)
      }
    },
    [],
  )

  const removeAttachment = useCallback((url: string) => {
    setAttachments((prev) => prev.filter((a) => a.url !== url))
  }, [])

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send(input)
    }
  }

  const turns = useMemo(() => {
    const groups: ActiveMessage[][] = []
    let current: ActiveMessage[] = []
    for (const m of messages) {
      if (m.role === 'user') {
        if (current.length) groups.push(current)
        current = [m]
      } else {
        current.push(m)
      }
    }
    if (current.length) groups.push(current)
    return groups
  }, [messages])

  const isMessageVisible = (m: ActiveMessage) => {
    if (m.role === 'user' || m.role === 'tool') return true
    if (m.error) return true
    const text = m.parts.filter((p) => p.type === 'text').map((p) => p.text ?? '').join('')
    const reasoning = m.parts.filter((p) => p.type === 'reasoning').map((p) => p.text ?? '').join('')
    if (text.trim() || reasoning.trim()) return true
    if (streaming && m.temp && m.role === 'assistant') return true
    return false
  }

  const renderMessage = (m: ActiveMessage, onDelete?: () => void) => {
    if (m.id === editingId && !streaming) {
      return (
        <EditBox
          key={m.id}
          value={editingText}
          onChange={setEditingText}
          onConfirm={() => void sendEdit(m.id, editingText)}
          onCancel={() => setEditingId(null)}
          confirmLabel="Send"
          align="right"
        />
      )
    }
    return (
      <MessageBubble
        key={m.id}
        message={m}
        username={username}
        onEdit={!streaming ? () => startEditMessage(m.id) : undefined}
        onDelete={!streaming && onDelete ? onDelete : undefined}
      />
    )
  }

  const renderAssistantTurn = (turn: ActiveMessage[]) => {
    const rows = turn.slice(1)
    const visible = rows.filter(isMessageVisible)
    if (visible.length === 0) return null
    const senderName = visible.find((m) => m.role === 'assistant')?.model || model || 'Assistant'
    const lastId = [...visible].reverse().find((m) => m.role === 'assistant')?.id
    const turnIds = turn.map((m) => m.id)
    if (lastId && lastId === editingId && !streaming) {
      return (
        <EditBox
          key={lastId}
          value={editingText}
          onChange={setEditingText}
          onConfirm={() => void saveEdit(lastId, editingText)}
          onCancel={() => setEditingId(null)}
          confirmLabel="Confirm"
          align="left"
        />
      )
    }
    const anyReasoning = visible.some((m) => m.parts.some((p) => p.type === 'reasoning'))
    const expectsReasoning = reasoning && (reasoningCap !== false || anyReasoning)
    return (
      <AssistantTurn
        key={lastId ?? 'assistant-turn'}
        rows={visible}
        senderName={senderName}
        isStreaming={streaming && visible.some((m) => m.temp)}
        expectsReasoning={expectsReasoning}
        activeTool={activeTool}
        onEdit={!streaming && lastId ? () => startEditMessage(lastId) : undefined}
        onDelete={!streaming ? () => void deleteMessage(turnIds) : undefined}
      />
    )
  }

  return (
    <Layout
      currentConversationId={conversationId}
      onSelectConversation={() => {}}
      onNewChat={startNewChat}
    >
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-3xl flex-col gap-5 px-4 py-6">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 pt-24 text-center">
                <div className="flex size-12 items-center justify-center rounded-2xl bg-indigo-700/20">
                  <Sparkles className="size-6 text-indigo-400" />
                </div>
                <h2 className="text-xl font-semibold text-zinc-100">Start a conversation</h2>
                <p className="max-w-md text-sm text-zinc-500">
                  Pick a model and ask anything. Knowledge, tools, skills, and memory are all
                  available — toggle them per conversation or manage them in Settings.
                </p>
              </div>
            ) : (
              turns.map((turn) => {
                const first = turn[0]
                if (first.role === 'user') {
                  return (
                    <Fragment key={first.id}>
                      {renderMessage(first, turn.length > 1 ? () => void deleteMessage(turn.map((m) => m.id)) : undefined)}
                      {renderAssistantTurn(turn)}
                    </Fragment>
                  )
                }
                return renderAssistantTurn(turn)
              })
            )}
            <div ref={scrollRef} />
          </div>
        </div>

        <div className="border-t border-zinc-800 bg-zinc-950/80 backdrop-blur">
          <div className="relative mx-auto max-w-3xl px-4 py-3">
            {savedNotice && (
              <div className="pointer-events-none absolute -top-9 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-indigo-600/40 bg-indigo-950/95 px-3 py-1 text-[11px] text-indigo-200 shadow-lg shadow-black/40">
                {savedNotice}
              </div>
            )}
            <div className="mb-2 flex items-center gap-2">
              <div className="flex items-center gap-2">
                <ComposerMenu
                  systemPrompt={systemPrompt}
                  temperature={temperature}
                  kbEnabled={kbEnabled}
                  memoryEnabled={memoryEnabled}
                  mcpTools={mcpTools}
                  mcpAllTools={allMcpTools ?? []}
                  onMcpToolToggle={toggleMcpTool}
                  presets={presets ?? []}
                  onKbToggle={toggleKb}
                  onMemoryToggle={toggleMemory}
                  onSystemPromptChange={setSystemPrompt}
                  onTemperatureChange={setTemperature}
                  onApplyPreset={(content) => setSystemPrompt(content)}
                  onAttachFiles={handleAttachFiles}
                  onResetPrompt={() => {
                    setSystemPrompt(
                      defaults?.default_system_prompt?.trim() ||
                        presets?.find((p) => p.name === 'default')?.content ||
                        '',
                    )
                    setTemperature(0.7)
                  }}
                />
                {showReasoningToggle && (
                  <button
                    type="button"
                    onClick={() => setReasoning((r) => !r)}
                    title={reasoning ? 'Reasoning enabled — click to turn off' : 'Reasoning disabled — click to turn on'}
                    className={`flex size-8 shrink-0 items-center justify-center rounded-lg border transition-colors ${
                      reasoning
                        ? 'border-indigo-700/50 bg-indigo-600/10 text-indigo-300'
                        : 'border-zinc-700 bg-zinc-900 text-zinc-500'
                    }`}
                  >
                    <Brain className="size-4" />
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setSearchEnabled((s) => !s)}
                  title={searchEnabled ? 'Web search & tools enabled — model can call tools itself' : 'Web search & tools disabled'}
                  className={`flex size-8 shrink-0 items-center justify-center rounded-lg border transition-colors ${
                    searchEnabled
                      ? 'border-indigo-700/50 bg-indigo-600/10 text-indigo-300'
                      : 'border-zinc-700 bg-zinc-900 text-zinc-500'
                  }`}
                >
                  <Globe className="size-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setCodeEnabled((s) => !s)}
                  title={codeEnabled ? 'Code execution enabled — you can ask me to run code' : 'Code execution disabled'}
                  className={`flex size-8 shrink-0 items-center justify-center rounded-lg border transition-colors ${
                    codeEnabled
                      ? 'border-indigo-700/50 bg-indigo-600/10 text-indigo-300'
                      : 'border-zinc-700 bg-zinc-900 text-zinc-500'
                  }`}
                >
                  <Terminal className="size-4" />
                </button>
              </div>
              <ModelSelector
                groups={groups}
                value={modelKey}
                onChange={handleModelChange}
                disabled={!hasModels}
              />
            </div>
            {showNoModelsNotice && (
              <div className="mb-2 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                No models available yet.
                <Link to="/settings" className="font-medium underline underline-offset-2">
                  Add a provider in Settings
                </Link>
              </div>
            )}
            {modelSwitchedFrom && (
              <div className="mb-2 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                <AlertTriangle className="size-3.5 shrink-0 text-amber-400" />
                <span>
                  <span className="font-medium text-amber-100">{modelSwitchedFrom}</span> is no longer available — switched
                  to {model || 'the default model'}.
                </span>
              </div>
            )}

            {attachments.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-2">
                {attachments.map((a) =>
                  a.mime.startsWith('image/') ? (
                    <div key={a.url} className="group relative">
                      <img
                        src={a.url}
                        alt="attachment"
                        className="size-16 rounded-lg border border-zinc-700 object-cover"
                      />
                      <button
                        type="button"
                        onClick={() => removeAttachment(a.url)}
                        className="absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full border border-zinc-600 bg-zinc-900 text-zinc-300 opacity-0 transition-opacity group-hover:opacity-100"
                      >
                        <X className="size-3" />
                      </button>
                    </div>
                  ) : (
                    <div key={a.url} className="group relative">
                      <div className="flex h-16 items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-800 px-3 text-xs text-zinc-300">
                        <FileText className="size-4 shrink-0 text-indigo-400" />
                        <span className="max-w-32 truncate">{a.name}</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeAttachment(a.url)}
                        className="absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full border border-zinc-600 bg-zinc-900 text-zinc-300 opacity-0 transition-opacity group-hover:opacity-100"
                      >
                        <X className="size-3" />
                      </button>
                    </div>
                  ),
                )}
              </div>
            )}

            <div className="flex items-end gap-2 rounded-2xl border border-zinc-700 bg-zinc-900 p-2 focus-within:border-indigo-600 focus-within:ring-2 focus-within:ring-indigo-600/20">
              <input
                ref={attachInputRef}
                type="file"
                multiple
                accept="image/*,.txt,.md,.csv,.pdf,.json,.xml"
                onChange={handleAttachChange}
                className="hidden"
              />
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={Math.min(6, Math.max(1, input.split('\n').length))}
                placeholder="Message…"
                className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 outline-none"
              />
              {streaming ? (
                <Button variant="outline" size="sm" onClick={stop} title="Stop generating">
                  <Square className="size-4" />
                </Button>
              ) : (
                <Button size="sm" onClick={() => void send(input)} disabled={attaching || ((!input.trim() && attachments.length === 0) || !modelKey)}>
                  <Send className="size-4" />
                </Button>
              )}
            </div>
            <p className="mt-2 text-center text-[11px] text-zinc-600">
              Hestia can make mistakes. Verify important information.
            </p>
          </div>
        </div>
      </div>
    </Layout>
  )
}
