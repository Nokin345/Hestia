import { create } from 'zustand'

interface ChatSettingsState {
  modelKey: string
  reasoning: boolean
  searchEnabled: boolean
  codeEnabled: boolean
  mcpTools: string[]
  kbEnabled: boolean
  memoryEnabled: boolean
  systemPrompt: string
  temperature: number
  modelSwitchedFrom: string | null
}

export const useChatSettingsStore = create<ChatSettingsState>()(() => ({
  modelKey: '',
  reasoning: true,
  searchEnabled: false,
  codeEnabled: false,
  mcpTools: [],
  kbEnabled: false,
  memoryEnabled: false,
  systemPrompt: '',
  temperature: 0.7,
  modelSwitchedFrom: null,
}))