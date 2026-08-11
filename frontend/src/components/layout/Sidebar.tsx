import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, CheckSquare, Database, MoreHorizontal, Pin, Pencil, PlugZap, Plus, Search, Settings, LogOut, Trash2, X } from 'lucide-react'
import { clsx } from 'clsx'
import { apiDelete, apiFetch, apiPatch, apiPost } from '../../api/client'
import type { Conversation } from '../../api/types'
import { useAuth } from '../../store/auth'
import { Button, ConfirmDialog } from '../ui'

const nav = [
  { to: '/knowledge-bases', label: 'Knowledge Bases', icon: BookOpen },
  { to: '/mcp', label: 'MCP', icon: PlugZap },
  { to: '/memories', label: 'Memories', icon: Database },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function groupLabel(ts: string): string {
  const now = new Date()
  const d = new Date(ts)
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startThat = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((startToday - startThat) / 86400000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days <= 30) return `${days} days ago`
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short' })
}

interface SidebarProps {
  currentConversationId: string | null
  onSelectConversation: (id: string) => void
  onNewChat: () => void
  open: boolean
  onClose: () => void
}

export function Sidebar({ currentConversationId, onSelectConversation, onNewChat, open, onClose }: SidebarProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const setAuth = useAuth((s) => s.setAuth)

  const { data: conversations } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => apiFetch<Conversation[]>('/conversations'),
  })

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const startNew = () => {
    onNewChat()
    navigate('/')
    onClose()
  }

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['conversations'] })

  const remove = async (id: string) => {
    await apiDelete(`/conversations/${id}`)
    invalidate()
    if (currentConversationId === id) navigate('/')
  }

  const togglePin = async (c: Conversation) => {
    await apiPatch(`/conversations/${c.id}`, { pinned: !c.pinned })
    invalidate()
  }

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAll = () => {
    const all = (conversations ?? []).map((c) => c.id)
    setSelected((prev) => (prev.size === all.length && all.length > 0 ? new Set() : new Set(all)))
  }

  const bulkDelete = async () => {
    const ids = [...selected]
    if (!ids.length) return
    setDeleting(true)
    try {
      await Promise.all(ids.map((id) => apiDelete(`/conversations/${id}`)))
      setSelected(new Set())
      setEditMode(false)
      invalidate()
      if (currentConversationId && selected.has(currentConversationId)) navigate('/')
    } finally {
      setDeleting(false)
      setConfirmDelete(false)
    }
  }
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameText, setRenameText] = useState('')
  const [editMode, setEditMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const renameRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const searchBtnRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!searchOpen) return
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        searchBtnRef.current?.contains(target) ||
        searchRef.current?.contains(target)
      ) {
        return
      }
      setSearchOpen(false)
      setSearchQuery('')
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [searchOpen])

  useEffect(() => {
    if (!menuFor) return
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuFor(null)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [menuFor])

  const startRename = (c: Conversation) => {
    setRenamingId(c.id)
    setRenameText(c.title)
    setMenuFor(null)
  }

  const saveRename = async (id: string) => {
    const title = renameText.trim()
    setRenamingId(null)
    if (!title) return
    await apiPatch(`/conversations/${id}`, { title })
    invalidate()
  }

  const logout = async () => {
    await apiPost('/auth/logout')
    setAuth(false, '')
    navigate('/login')
  }

  useEffect(() => {
    if (renamingId) renameRef.current?.focus()
  }, [renamingId])

  const grouped = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    const list = (conversations ?? []).filter(
      (c) => !q || c.title.toLowerCase().includes(q),
    )
    const pinned = list.filter((c) => c.pinned)
    const rest = list.filter((c) => !c.pinned)
    const groups: { label: string; items: Conversation[] }[] = []
    if (pinned.length) groups.push({ label: 'Pinned', items: pinned })
    for (const c of rest) {
      const label = groupLabel(c.updated_at)
      const last = groups[groups.length - 1]
      if (last && last.label === label) last.items.push(c)
      else groups.push({ label, items: [c] })
    }
    return groups
  }, [conversations, searchQuery])

  return (
    <div
      className={clsx(
        'fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-zinc-800 bg-zinc-950 transition-transform lg:static lg:translate-x-0',
        open ? 'translate-x-0' : '-translate-x-full',
      )}
    >
      <div className="flex items-center justify-between px-4 py-4">
        <div className="flex items-center gap-2">
          <img src="/favicon.svg" className="size-7" alt="" />
          <span className="text-sm font-semibold">Hestia</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => {
              setEditMode((v) => !v)
              setSelected(new Set())
              setMenuFor(null)
            }}
            className={clsx(
              'rounded-md p-1.5 text-zinc-400 transition-colors hover:text-zinc-100',
              editMode && 'bg-zinc-800 text-indigo-300',
            )}
            title="Edit conversations"
          >
            <Pencil className="size-4" />
          </button>
          <button
            ref={searchBtnRef}
            onClick={() => {
              setSearchOpen((v) => !v)
              setSearchQuery('')
            }}
            className={clsx(
              'rounded-md p-1.5 text-zinc-400 transition-colors hover:text-zinc-100',
              searchOpen && 'bg-zinc-800 text-indigo-300',
            )}
            title="Search conversations"
          >
            <Search className="size-4" />
          </button>
          <button className="text-zinc-400 hover:text-zinc-100 lg:hidden" onClick={onClose}>
            <X className="size-5" />
          </button>
        </div>
      </div>

      {searchOpen && (
        <div className="px-3 pb-3">
          <input
            ref={searchRef}
            autoFocus
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setSearchOpen(false)
                setSearchQuery('')
              }
            }}
            placeholder="Search conversations…"
            className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 outline-none transition-colors focus:border-indigo-600 focus:ring-2 focus:ring-indigo-600/30"
          />
        </div>
      )}

      {editMode ? (
        <div className="flex items-center justify-between gap-2 px-3">
          <button
            onClick={selectAll}
            className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-zinc-300 transition-colors hover:bg-zinc-900 hover:text-zinc-100"
          >
            <CheckSquare className="size-3.5" />
            {selected.size === (conversations ?? []).length && (conversations ?? []).length > 0
              ? 'Deselect all'
              : 'Select all'}
          </button>
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-500">{selected.size} selected</span>
            <button
              onClick={() => setConfirmDelete(true)}
              disabled={selected.size === 0}
              className="flex items-center gap-1.5 rounded-lg bg-red-600/15 px-2 py-1.5 text-xs text-red-400 transition-colors hover:bg-red-600/25 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Trash2 className="size-3.5" /> Delete
            </button>
          </div>
        </div>
      ) : (
        <div className="px-3">
          <Button className="w-full" onClick={startNew}>
            <Plus className="size-4" /> New chat
          </Button>
        </div>
      )}

      <div className="mt-4 flex-1 overflow-y-auto px-3 pb-4">
        {grouped.length === 0 && (
          <p className="px-3 py-2 text-xs text-zinc-600">
            {(conversations ?? []).length === 0
              ? 'No conversations yet'
              : 'No matching conversations'}
          </p>
        )}
        {grouped.map((group) => (
          <div key={group.label} className="mb-3">
            <div className="flex items-center gap-2 px-3 pb-1 pt-2">
              <span className="text-[10px] font-medium uppercase tracking-wider text-zinc-600">
                {group.label}
              </span>
            </div>
            <div className="space-y-0.5">
              {group.items.map((c) => (
                <div key={c.id} className="group relative">
                  {renamingId === c.id ? (
                    <input
                      ref={renameRef}
                      value={renameText}
                      onChange={(e) => setRenameText(e.target.value)}
                      onBlur={() => saveRename(c.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') saveRename(c.id)
                        if (e.key === 'Escape') setRenamingId(null)
                      }}
                      className="w-full rounded-lg border border-indigo-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none"
                    />
                  ) : editMode ? (
                    <button
                      onClick={() => toggleSelect(c.id)}
                      className={clsx(
                        'flex w-full items-center gap-2.5 rounded-lg py-2 pl-3 pr-10 text-left text-sm',
                        selected.has(c.id)
                          ? 'bg-indigo-600/15 text-indigo-200'
                          : 'text-zinc-300 hover:bg-zinc-900 hover:text-zinc-100',
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(c.id)}
                        onChange={() => toggleSelect(c.id)}
                        onClick={(e) => e.stopPropagation()}
                        className="size-4 shrink-0 accent-indigo-600"
                      />
                      <span className="truncate">{c.title}</span>
                    </button>
                  ) : (
                    <>
                      <button
                        onClick={() => {
                          onSelectConversation(c.id)
                          navigate(`/?c=${c.id}`)
                          onClose()
                        }}
                        className={clsx(
                          'w-full truncate rounded-lg py-2 pl-3 pr-10 text-left text-sm text-zinc-300 hover:bg-zinc-900 hover:text-zinc-100',
                          currentConversationId === c.id && 'bg-zinc-900 text-zinc-100',
                        )}
                      >
                        <span className="inline-flex items-center gap-1.5">
                          {c.pinned && <Pin className="size-3 shrink-0 text-indigo-400" />}
                          <span className="truncate">{c.title}</span>
                        </span>
                      </button>
                      {!editMode && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setMenuFor(menuFor === c.id ? null : c.id)
                          }}
                          className="absolute right-2 top-1/2 hidden -translate-y-1/2 rounded p-0.5 text-zinc-500 hover:text-zinc-200 group-hover:block"
                          title="Options"
                        >
                          <MoreHorizontal className="size-4" />
                        </button>
                      )}
                      {menuFor === c.id && (
                        <div
                          ref={menuRef}
                          className="absolute right-1 top-full z-50 mt-1 w-40 rounded-lg border border-zinc-700 bg-zinc-900/95 py-1 shadow-2xl shadow-black/50 backdrop-blur"
                        >
                            <button
                              onClick={() => togglePin(c)}
                              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-zinc-200 hover:bg-zinc-800"
                            >
                              <Pin className="size-3.5" />
                              {c.pinned ? 'Unpin' : 'Pin'}
                            </button>
                            <button
                              onClick={() => startRename(c)}
                              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-zinc-200 hover:bg-zinc-800"
                            >
                              <Pencil className="size-3.5" />
                              Rename
                            </button>
                            <div className="my-1 h-px bg-zinc-800" />
                            <button
                              onClick={() => remove(c.id)}
                              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-red-400 hover:bg-red-500/10"
                            >
                              <Trash2 className="size-3.5" />
                              Delete
                            </button>
                          </div>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-zinc-800 px-3 py-3">
        {nav.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-zinc-300 hover:bg-zinc-900 hover:text-zinc-100',
                isActive && 'bg-zinc-900 text-zinc-100',
              )
            }
          >
            <Icon className="size-4" /> {label}
          </NavLink>
        ))}
        <button
          onClick={logout}
          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
        >
          <LogOut className="size-4" /> Log out
        </button>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete conversations"
        message={`This will permanently delete ${selected.size} conversation${selected.size === 1 ? '' : 's'}.`}
        confirmLabel={deleting ? 'Deleting…' : 'Delete'}
        loading={deleting}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => void bulkDelete()}
      />
    </div>
  )
}
