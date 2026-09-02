import { create } from 'zustand'

interface StreamingState {
  streaming: boolean
  activeTool: string | null
}

export const useStreamingStore = create<StreamingState>()(() => ({
  streaming: false,
  activeTool: null,
}))