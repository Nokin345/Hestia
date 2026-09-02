import { create } from 'zustand'

interface EditingState {
  editingId: string | null
  editingText: string
  editingAttachments: { url: string; mime: string; name?: string; text?: string }[]
}

export const useEditingStore = create<EditingState>()(() => ({
  editingId: null,
  editingText: '',
  editingAttachments: [],
}))