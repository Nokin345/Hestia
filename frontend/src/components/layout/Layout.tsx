import type { ReactNode } from 'react'
import { useState } from 'react'
import { Sidebar } from './Sidebar'

interface LayoutProps {
  children: ReactNode
  currentConversationId?: string | null
  onSelectConversation?: (id: string) => void
  onNewChat?: () => void
}

export function Layout({ children, currentConversationId = null, onSelectConversation, onNewChat }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="flex h-dvh overflow-hidden bg-zinc-950">
      <Sidebar
        currentConversationId={currentConversationId}
        onSelectConversation={onSelectConversation ?? (() => {})}
        onNewChat={onNewChat ?? (() => {})}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <main className="relative flex min-w-0 flex-1 flex-col">
        <div className="flex items-center border-b border-zinc-800 px-4 py-3 lg:hidden">
          <button onClick={() => setSidebarOpen(true)} className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-900">
            <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 6h18M3 12h18M3 18h18" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        {children}
      </main>
      {sidebarOpen && (
        <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}
    </div>
  )
}
