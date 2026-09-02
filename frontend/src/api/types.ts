export interface ProviderModel {
  id: string
  name?: string
  context_window: number | null
  vision: boolean
  max_output: number | null
  available?: boolean
  reason?: string
}

export interface ModelEntry {
  id: string
  provider_id: string
  provider_name: string
  vision: boolean
  context_window: number | null
}

export interface ProviderTypeMeta {
  id: string
  name: string
  requires_base_url: boolean
  default_base_url: string
  requires_api_key: boolean
}

export interface Provider {
  id: string
  name: string
  type: string
  base_url: string | null
  api_key_masked: string
  enabled: boolean
  allowed_models: ProviderModel[] | null
}

export interface ProviderTestResult {
  ok: boolean
  message: string
  models: ProviderModel[]
}

export interface SearchConfig {
  searxng_url: string
  max_results: number
  fallback: boolean
  fetch_urls: boolean
  fetch_limit: number
  max_chars_per_url: number
}

export interface DefaultsConfig {
  default_kb_enabled: boolean
  default_memory_enabled: boolean
  default_search_enabled: boolean
  default_code_enabled: boolean
  default_mcp_enabled: boolean
  default_model: string
  utility_model: string
  default_system_prompt: string
}

export interface SystemPromptPreset {
  id: string
  name: string
  content: string
}

export interface SearchResult {
  title: string
  url: string
  snippet: string
}

export interface SearchFetched {
  url: string
  title: string
  text_chars: number
}

export interface SearchPayload {
  engine: string
  results: SearchResult[]
  fetched: SearchFetched[]
}

export interface SearchTestResult {
  ok: boolean
  message: string
  engine: string
  results: number
}

export interface McpHeader {
  key: string
  value: string
}

export interface McpServer {
  id: string
  name: string
  transport: 'http' | 'sse'
  url: string
  auth_token: string
  headers: McpHeader[]
  enabled: boolean
  disabled_tools: string[]
  created_at: string
  updated_at: string
}

export interface McpToolDef {
  name: string
  server: string
  raw_name: string
  description: string
  input_schema: Record<string, unknown>
}

export interface McpServerTestResult {
  ok: boolean
  message: string
  tools: McpToolDef[]
}

export interface Conversation {
  id: string
  title: string
  provider: string
  model: string
  skill_id: string | null
  pinned: boolean
  kb_enabled: boolean
  memory_enabled: boolean
  reasoning_enabled: boolean
  search_enabled: boolean
  code_enabled: boolean
  mcp_tools: string[]
  system_prompt?: string | null
  temperature?: number | null
  created_at: string
  updated_at: string
}

export interface MessagePart {
  type: string
  text?: string
  image_url?: string | null
  image_mime?: string | null
  name?: string | null
  url?: string | null
}

export interface ChatUsage {
  input_tokens?: number | null
  output_tokens?: number | null
  total_tokens?: number | null
  tokens_per_second?: number | null
  reasoning_tokens?: number | null
}

export interface Message {
  id: string
  conversation_id: string
  role: string
  parts: MessagePart[]
  model?: string | null
  tool_calls?: { id: string; name: string; arguments: Record<string, unknown> }[]
  usage?: ChatUsage | null
  memories_used?: { id: string; text: string; category: string; type: 'pinned' | 'recalled' }[] | null
  kb_sources?: { filename: string; similarity: number; role: string }[] | null
  kb_line_ranges?: Record<string, [number, number][]> | null
  error?: string | null
  created_at: string
}

export const MEMORY_CATEGORIES = ['fact', 'event', 'contact', 'preference', 'identity'] as const
export type MemoryCategory = (typeof MEMORY_CATEGORIES)[number]

export interface Memory {
  id: string
  text: string
  category: MemoryCategory
  source: 'manual' | 'inline' | 'auto'
  uses: number
  pinned: boolean
  conversation_id: string | null
  created_at: string
  updated_at: string
  last_recalled_at: string | null
}

export interface MemoryStats {
  total: number
  categories: Record<string, number>
}

export interface OcrConfig {
  url: string
  model: string
  has_api_key: boolean
}

export interface OcrTestResult {
  ok: boolean
  message: string
  backend: string
  model: string
  fallback: boolean
  remote_reachable: boolean | null
}

export interface EmbeddingStats {
  healthy: boolean
  count: number
  lane: string | null
  dimension: number | null
}

export interface KbDocument {
  id: string
  filename: string
  mime: string
  chunk_count: number
  enabled: boolean
  preview: string
  extraction_method: string
  created_at: string
  url: string
}

export interface KbListResult {
  healthy: boolean
  stats: EmbeddingStats & { dimension: number | null }
  documents: KbDocument[]
}
