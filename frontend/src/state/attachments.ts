import { create } from 'zustand'

interface AttachmentState {
  attachments: { url: string; mime: string; name?: string; text?: string }[]
  attaching: boolean
  dragging: boolean
}

export const useAttachmentStore = create<AttachmentState>()(() => ({
  attachments: [],
  attaching: false,
  dragging: false,
}))