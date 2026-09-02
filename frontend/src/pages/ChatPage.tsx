import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Send, Square, Sparkles, Brain, Globe, Terminal, AlertTriangle, Plus } from 'lucide-react'
import { apiFetch, apiPatch, apiDelete, apiPost, apiUpload } from '../api/client'
import { streamChat } from '../api/stream'
import { readLastModels, writeLastModels } from '../persist'
import type { ChatEventData, KbSource, RetrievedMemory } from '../api/stream'
import type { ChatUsage, Conversation, DefaultsConfig, McpToolDef, Message, ModelEntry, SystemPromptPreset } from '../api/types'
import { AttachmentChip } from '../components/chat/AttachmentChip'
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
  kbLineRanges?: Record<string, [number, number][]>
}

type Attachment = { url: string; mime: string; name?: string; text?: string }

function attachmentParts(attachments: Attachment[]): { type: string; text?: string; image_url?: string; image_mime?: string; name?: string; url?: string }[] {
  const parts: { type: string; text?: string; image_url?: string; image_mime?: string; name?: string; url?: string }[] = []
  for (const a of attachments) {
    if (a.mime.startsWith('image/')) {
      parts.push({ type: 'image_url', image_url: a.url, image_mime: a.mime })
    } else {
      parts.push({ type: 'document', url: a.url, name: a.name ?? a.url, text: a.text })
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

import { useChatSettingsStore } from '../state/chatSettings'
import { useEditingStore } from '../state/editing'
import { useAttachmentStore } from '../state/attachments'
import { useStreamingStore } from '../state/streaming'

export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const conversationId = searchParams.get('c')
  const username = useAuth((s) => s.username)

  const [messages, setMessages] = useState<ActiveMessage[]>([])
  const [input, setInput] = useState('')

  const streaming = useStreamingStore((s) => s.streaming)
  const setStreaming = (v: boolean | ((prev: boolean) => boolean)) => {
    const value = typeof v === 'function' ? v(useStreamingStore.getState().streaming) : v
    useStreamingStore.setState({ streaming: value })
  }
  const activeTool = useStreamingStore((s) => s.activeTool)
  const setActiveTool = (v: string | null | ((prev: string | null) => string | null)) => {
    const value = typeof v === 'function' ? v(useStreamingStore.getState().activeTool) : v
    useStreamingStore.setState({ activeTool: value })
  }

  const modelKey = useChatSettingsStore((s) => s.modelKey)
  const setModelKey = (v: string | ((prev: string) => string)) => {
    const value = typeof v === 'function' ? v(useChatSettingsStore.getState().modelKey) : v
    useChatSettingsStore.setState({ modelKey: value })
  }
  const reasoning = useChatSettingsStore((s) => s.reasoning)
  const setReasoning = (v: boolean | ((prev: boolean) => boolean)) => {
    const value = typeof v === 'function' ? v(useChatSettingsStore.getState().reasoning) : v
    useChatSettingsStore.setState({ reasoning: value })
  }
  const searchEnabled = useChatSettingsStore((s) => s.searchEnabled)
  const setSearchEnabled = (v: boolean | ((prev: boolean) => boolean)) => {
    const value = typeof v === 'function' ? v(useChatSettingsStore.getState().searchEnabled) : v
    useChatSettingsStore.setState({ searchEnabled: value })
  }
  const codeEnabled = useChatSettingsStore((s) => s.codeEnabled)
  const setCodeEnabled = (v: boolean | ((prev: boolean) => boolean)) => {
    const value = typeof v === 'function' ? v(useChatSettingsStore.getState().codeEnabled) : v
    useChatSettingsStore.setState({ codeEnabled: value })
  }
  const mcpTools = useChatSettingsStore((s) => s.mcpTools)
  const setMcpTools = (v: string[] | ((prev: string[]) => string[])) => {
    const value = typeof v === 'function' ? v(useChatSettingsStore.getState().mcpTools) : v
    useChatSettingsStore.setState({ mcpTools: value })
  }
  const kbEnabled = useChatSettingsStore((s) => s.kbEnabled)
  const setKbEnabled = (v: boolean | ((prev: boolean) => boolean)) => {
    const value = typeof v === 'function' ? v(useChatSettingsStore.getState().kbEnabled) : v
    useChatSettingsStore.setState({ kbEnabled: value })
  }
  const memoryEnabled = useChatSettingsStore((s) => s.memoryEnabled)
  const setMemoryEnabled = (v: boolean | ((prev: boolean) => boolean)) => {
    const value = typeof v === 'function' ? v(useChatSettingsStore.getState().memoryEnabled) : v
    useChatSettingsStore.setState({ memoryEnabled: value })
  }
  const modelSwitchedFrom = useChatSettingsStore((s) => s.modelSwitchedFrom)
  const setModelSwitchedFrom = (v: string | null | ((prev: string | null) => string | null)) => {
    const value = typeof v === 'function' ? v(useChatSettingsStore.getState().modelSwitchedFrom) : v
    useChatSettingsStore.setState({ modelSwitchedFrom: value })
  }
  const systemPrompt = useChatSettingsStore((s) => s.systemPrompt)
  const setSystemPrompt = (v: string | ((prev: string) => string)) => {
    const value = typeof v === 'function' ? v(useChatSettingsStore.getState().systemPrompt) : v
    useChatSettingsStore.setState({ systemPrompt: value })
  }
  const temperature = useChatSettingsStore((s) => s.temperature)
  const setTemperature = (v: number | ((prev: number) => number)) => {
    const value = typeof v === 'function' ? v(useChatSettingsStore.getState().temperature) : v
    useChatSettingsStore.setState({ temperature: value })
  }

  const editingId = useEditingStore((s) => s.editingId)
  const setEditingId = (v: string | null | ((prev: string | null) => string | null)) => {
    const value = typeof v === 'function' ? v(useEditingStore.getState().editingId) : v
    useEditingStore.setState({ editingId: value })
  }
  const editingText = useEditingStore((s) => s.editingText)
  const setEditingText = (v: string | ((prev: string) => string)) => {
    const value = typeof v === 'function' ? v(useEditingStore.getState().editingText) : v
    useEditingStore.setState({ editingText: value })
  }
  const editingAttachments = useEditingStore((s) => s.editingAttachments)
  const setEditingAttachments = (v: { url: string; mime: string; name?: string; text?: string }[] | ((prev: { url: string; mime: string; name?: string; text?: string }[]) => { url: string; mime: string; name?: string; text?: string }[])) => {
    const value = typeof v === 'function' ? v(useEditingStore.getState().editingAttachments) : v
    useEditingStore.setState({ editingAttachments: value })
  }

  const attachments = useAttachmentStore((s) => s.attachments)
  const setAttachments = (v: { url: string; mime: string; name?: string; text?: string }[] | ((prev: { url: string; mime: string; name?: string; text?: string }[]) => { url: string; mime: string; name?: string; text?: string }[])) => {
    const value = typeof v === 'function' ? v(useAttachmentStore.getState().attachments) : v
    useAttachmentStore.setState({ attachments: value })
  }
  const attaching = useAttachmentStore((s) => s.attaching)
  const setAttaching = (v: boolean | ((prev: boolean) => boolean)) => {
    const value = typeof v === 'function' ? v(useAttachmentStore.getState().attaching) : v
    useAttachmentStore.setState({ attaching: value })
  }
  const dragging = useAttachmentStore((s) => s.dragging)
  const setDragging = (v: boolean | ((prev: boolean) => boolean)) => {
    const value = typeof v === 'function' ? v(useAttachmentStore.getState().dragging) : v
    useAttachmentStore.setState({ dragging: value })
  }
  const attachInputRef = useRef<HTMLInputElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const wakeLockRef = useRef<WakeLockSentinel | null>(null)

  const acquireWakeLock = async () => {
    try {
      const lock = await navigator.wakeLock.request('screen')
      wakeLockRef.current = lock
      lock.addEventListener('release', () => {
        wakeLockRef.current = null
      })
    } catch {
      // Wake lock not supported or denied
    }
  }

  const releaseWakeLock = () => {
    wakeLockRef.current?.release().catch(() => {})
    wakeLockRef.current = null
  }
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [input])
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  // Keep the most recent retrieved-memory set in a ref so it can be reattached
  // to the assistant message after a conversation reload (e.g. the first-message
  // URL change to ?c=...) without losing the pill.
  const retrievedStoreRef = useRef<Record<string, RetrievedMemory[]>>({})
  const kbStoreRef = useRef<Record<string, KbSource[]>>({})
  const kbLineRangesRef = useRef<Record<string, Record<string, [number, number][]>>>({})
  const reattachRetrieved = useCallback(
    (list: Message[]): ActiveMessage[] => {
      const store = retrievedStoreRef.current
      const kbs = kbStoreRef.current
      const lineRanges = kbLineRangesRef.current

      function attachField(
        msg: ActiveMessage,
        field: 'retrievedMemories' | 'retrievedKb' | 'kbLineRanges',
        persisted: any,
        localStore: Record<string, any>,
      ) {
        if (persisted && persisted.length > 0) {
          msg[field] = persisted
        } else if (msg.role === 'assistant' && localStore[msg.id]) {
          msg[field] = localStore[msg.id]
        }
      }

      const merged = list.map((m) => {
        const active = { ...m, temp: false } as ActiveMessage
        attachField(active, 'retrievedMemories', m.memories_used, store)
        attachField(active, 'retrievedKb', m.kb_sources, kbs)
        attachField(active, 'kbLineRanges', m.kb_line_ranges, lineRanges)
        return active
      })

      // Fallback: if no message has retrieved data, attach to the last assistant message
      function attachLatest(
        field: 'retrievedMemories' | 'retrievedKb' | 'kbLineRanges',
        localStore: Record<string, any>,
      ) {
        if (Object.keys(localStore).length === 0) return
        const entries = Object.entries(localStore)
        const [, latest] = entries[entries.length - 1]
        const hasAny = merged.some((m) => (m as any)[field]?.length)
        if (!hasAny) {
          for (let i = merged.length - 1; i >= 0; i--) {
            if (merged[i].role === 'assistant') {
              (merged[i] as any)[field] = latest
              break
            }
          }
        }
      }

      attachLatest('retrievedMemories', store)
      attachLatest('retrievedKb', kbs)
      attachLatest('kbLineRanges', lineRanges)

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

const toggleKb = () => {
    const next = !kbEnabled
    setKbEnabled(next)
    if (!conversationId) return
    apiPatch(`/conversations/${conversationId}`, { kb_enabled: next }).catch(() => {})
  }

  const toggleMemory = () => {
    const next = !memoryEnabled
    setMemoryEnabled(next)
    if (!conversationId) return
    apiPatch(`/conversations/${conversationId}`, { memory_enabled: next }).catch(() => {})
  }

  const toggleMcpTool = (toolName: string) => {
    const next = mcpTools.includes(toolName)
      ? mcpTools.filter((n) => n !== toolName)
      : [...mcpTools, toolName]
    setMcpTools(next)
  }

  const handleModelChange = (key: string) => {
    setModelKey(key)
    setModelSwitchedFrom(null)
    if (!conversationId) return
    const parsed = parseModelKey(key)
    apiPatch(`/conversations/${conversationId}`, {
      provider: parsed.provider,
      model: parsed.model,
    }).catch(() => {})
  }

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

  const stop = () => {
    const convId = searchParams.get('c') || realConvIdRef.current
    const aiId = aiIdRef.current
    if (aiId && convId) {
      setMessages((prev) => {
        const m = prev.find((msg) => msg.id === aiId)
        if (m) {
          const textParts = m.parts.filter(
            (p) => p.type === 'text' || p.type === 'reasoning',
          )
          if (textParts.length > 0) {
            apiPost(`/conversations/${convId}/messages/partial`, textParts).catch(
              () => {},
            )
          }
        }
        return prev
      })
    }
    abortRef.current?.abort()
    if (!convId) return
    window.setTimeout(() => {
      apiFetch<Message[]>(`/conversations/${convId}/messages`)
        .then((list) => {
          setMessages(reattachRetrieved(list))
          if (searchParams.get('c') !== convId) {
            setSearchParams({ c: convId }, { replace: true })
          }
        })
        .catch(() => {})
    }, 500)
  }

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
  const upsertAssistant = (apply: (m: ActiveMessage) => ActiveMessage) => {
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
    }

  const handleStreamEvent = () => (e: ChatEventData) => {
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
      } else if (e.event === 'kb_retrieved') {
        const id = target()
        if (!id) return
        const sources = e.data.sources ?? []
        const lineRanges = e.data.line_ranges ?? {}
        kbStoreRef.current = { [id]: sources }
        kbLineRangesRef.current = { [id]: lineRanges }
        setMessages((prev) =>
          prev.map((m) =>
            m.id === id
              ? { ...m, retrievedKb: sources.length ? sources : undefined, kbLineRanges: Object.keys(lineRanges).length ? lineRanges : undefined }
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
    }

  const send = async (text: string) => {
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
      setAttachments([])
      setStreaming(true)
      void acquireWakeLock()
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
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiIdRef.current ? { ...m, error: (err as Error).message } : m,
            ),
          )
        }
      } finally {
        releaseWakeLock()
        setStreaming(false)
        abortRef.current = null
        queryClient.invalidateQueries({ queryKey: ['conversations'] })
      }
    }

  const sendEdit = async (messageId: string, newText: string) => {
      if (!conversationId || streaming) return
      const content = newText.trim()
      if (!content) return
      setEditingId(null)
      setEditingAttachments([])
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
      void acquireWakeLock()
      aiIdRef.current = tempAssistant.id

      const controller = new AbortController()
      abortRef.current = controller

      try {
        await streamChat(
          {
            conversation_id: conversationId,
            content,
            parts: attachmentParts(editingAttachments),
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
        releaseWakeLock()
        setStreaming(false)
        abortRef.current = null
        queryClient.invalidateQueries({ queryKey: ['conversations'] })
      }
    }

  const startEditMessage = (messageId: string) => {
      const m = messages.find((x) => x.id === messageId)
      if (!m) return
      const text = m.parts
        .filter((p) => p.type === 'text')
        .map((p) => p.text ?? '')
        .join('')
      const attach = m.parts
        .filter((p) => p.type !== 'text' && p.type !== 'reasoning')
        .map((p) => ({
          url: p.image_url || p.url || '',
          mime: p.image_mime || 'application/octet-stream',
          name: p.name || undefined,
          text: p.text || undefined,
        }))
        .filter((a) => a.url)
      setEditingId(messageId)
      setEditingText(text)
      setEditingAttachments(attach)
    }

  const saveEdit = async (messageId: string, newText: string) => {
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
    }

  const deleteMessage = async (messageIds: string[]) => {
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
    }

  const startNewChat = () => {
    if (abortRef.current) abortRef.current.abort()
    setSearchParams({}, { replace: true })
    setMessages([])
    setInput('')
    setEditingId(null)
    setModelSwitchedFrom(null)
    retrievedStoreRef.current = {}
  }

  const handleAttachFiles = () => {
    attachInputRef.current?.click()
  }

  const uploadFiles = async (files: File[]) => {
      if (!files.length) return
      let convoId = conversationId
      try {
        // New-chat uploads need a conversation to live under (/uploads/<id>/).
        // Create one up front so the conversation-folder deletion logic applies.
        if (!convoId) {
          const conv = await apiPost<Conversation>('/conversations')
          convoId = conv.id
          realConvIdRef.current = convoId
          setSearchParams({ c: convoId }, { replace: true })
          queryClient.invalidateQueries({ queryKey: ['conversations'] })
        }
      } catch (err) {
        alert((err as Error).message)
        return
      }
      setAttaching(true)
      const results: { url: string; mime: string; name?: string; text?: string }[] = []
      try {
        for (const file of files) {
          const res = await apiUpload(file, convoId)
          results.push({ url: res.url, mime: res.mime, name: file.name, text: res.text })
        }
        if (editingId) {
          setEditingAttachments((prev) => [...prev, ...results])
        } else {
          setAttachments((prev) => [...prev, ...results])
        }
      } catch (err) {
        alert((err as Error).message)
      } finally {
        setAttaching(false)
      }
    }

  const handleAttachChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? [])
      e.target.value = ''
      await uploadFiles(files)
    }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setDragging(false)
      const files = Array.from(e.dataTransfer.files ?? [])
      void uploadFiles(files)
    }

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    if (e.currentTarget.contains(e.relatedTarget as Node)) return
    setDragging(false)
  }

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const files = Array.from(e.clipboardData?.files ?? [])
      if (!files.length) return
      e.preventDefault()
      void uploadFiles(files)
    }

  const removeAttachment = (url: string) => {
    setAttachments((prev) => prev.filter((a) => a.url !== url))
  }

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
        <div key={m.id} className="flex w-full flex-col items-end gap-2">
          {editingAttachments.length > 0 && (
            <div className="flex max-w-[85%] flex-wrap justify-end gap-2">
              {editingAttachments.map((a) => (
                <AttachmentChip
                  key={a.url}
                  attachment={a}
                  onRemove={() => setEditingAttachments((prev) => prev.filter((x) => x.url !== a.url))}
                  imageClassName="size-20 rounded-lg border border-zinc-700 object-cover"
                  containerClassName="flex h-20 items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-800 px-3 text-xs text-zinc-300"
                />
              ))}
              <button
                type="button"
                onClick={() => attachInputRef.current?.click()}
                className="flex size-20 items-center justify-center rounded-lg border border-dashed border-zinc-700 text-zinc-500 transition-colors hover:border-zinc-500 hover:text-zinc-300"
              >
                <Plus className="size-5" />
              </button>
            </div>
          )}
          {editingAttachments.length === 0 && (
            <button
              type="button"
              onClick={() => attachInputRef.current?.click()}
              className="flex items-center gap-1 rounded-lg border border-dashed border-zinc-700 px-3 py-1.5 text-xs text-zinc-500 transition-colors hover:border-zinc-500 hover:text-zinc-300"
            >
              <Plus className="size-3.5" /> Attach files
            </button>
          )}
          <EditBox
            value={editingText}
            onChange={setEditingText}
            onConfirm={() => void sendEdit(m.id, editingText)}
            onCancel={() => { setEditingId(null); setEditingAttachments([]) }}
            confirmLabel="Send"
            align="right"
          />
        </div>
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
    const assistantIds = rows.map((m) => m.id)
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
        onDelete={!streaming ? () => void deleteMessage(assistantIds) : undefined}
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
                      {renderMessage(first, () => void deleteMessage([first.id]))}
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
              {attachments.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-2">
                  {attachments.map((a) => (
                    <AttachmentChip
                      key={a.url}
                      attachment={a}
                      onRemove={() => removeAttachment(a.url)}
                    />
                  ))}
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

            <div
              className={`relative flex items-end gap-2 rounded-2xl border bg-zinc-900 p-2 focus-within:border-indigo-600 focus-within:ring-2 focus-within:ring-indigo-600/20 ${
                dragging ? 'border-indigo-500 ring-2 ring-indigo-500/30' : 'border-zinc-700'
              }`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              {dragging && (
                <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-2xl border-2 border-dashed border-indigo-400 bg-indigo-950/70">
                  <span className="flex items-center gap-2 text-sm font-medium text-indigo-200">
                    <Plus className="size-4" /> Drop to attach
                  </span>
                </div>
              )}
              <input
                ref={attachInputRef}
                type="file"
                multiple
                accept="image/*,.txt,.md,.csv,.pdf,.json,.xml"
                onChange={handleAttachChange}
                className="hidden"
              />
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                onPaste={handlePaste}
                rows={1}
                placeholder="Message…"
                className="max-h-[5rem] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 outline-none"
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
