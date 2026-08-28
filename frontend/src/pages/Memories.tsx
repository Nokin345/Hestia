import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Brain, Check, Loader2, MoreVertical, Pencil, Pin, Plus, Trash2, X } from 'lucide-react'
import { clsx } from 'clsx'
import { apiDelete, apiFetch, apiPatch, apiPost } from '../api/client'
import type { Memory, MemoryCategory, MemoryStats } from '../api/types'
import { MEMORY_CATEGORIES } from '../api/types'
import { Layout } from '../components/layout/Layout'
import { Button, ConfirmDialog, Textarea } from '../components/ui'

const CATEGORY_COLORS: Record<MemoryCategory, string> = {
  fact: 'bg-sky-500/15 text-sky-300',
  event: 'bg-amber-500/15 text-amber-300',
  contact: 'bg-emerald-500/15 text-emerald-300',
  preference: 'bg-pink-500/15 text-pink-300',
  identity: 'bg-indigo-500/15 text-indigo-300',
}

const SOURCE_LABELS: Record<Memory['source'], string> = {
  manual: 'manual',
  inline: 'remember',
  auto: 'auto',
}

function ActionMenu({
  pinned,
  onPin,
  onEdit,
  onDelete,
}: {
  pinned: boolean
  onPin: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const run = (fn: () => void) => () => {
    setOpen(false)
    fn()
  }

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="rounded-lg p-2 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
        title="Actions"
        aria-label="Memory actions"
      >
        <MoreVertical className="size-4" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-40 rounded-lg border border-zinc-700 bg-zinc-900/95 py-1 shadow-2xl shadow-black/50 backdrop-blur">
          <button
            type="button"
            onClick={run(onPin)}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-800"
          >
            <Pin className={`size-4 ${pinned ? 'text-indigo-400' : 'text-zinc-400'}`} />
            {pinned ? 'Unpin' : 'Pin'}
          </button>
          <button
            type="button"
            onClick={run(onEdit)}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-800"
          >
            <Pencil className="size-4 text-zinc-400" />
            Edit
          </button>
          <button
            type="button"
            onClick={run(onDelete)}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-400 hover:bg-red-500/10"
          >
            <Trash2 className="size-4" />
            Delete
          </button>
        </div>
      )}
    </div>
  )
}

export default function MemoriesPage() {
  const queryClient = useQueryClient()
  const { data: memories, isLoading } = useQuery({
    queryKey: ['memories'],
    queryFn: () => apiFetch<Memory[]>('/memories'),
  })
  const { data: stats } = useQuery({
    queryKey: ['memory-stats'],
    queryFn: () => apiFetch<MemoryStats>('/memories/stats'),
  })

  const [text, setText] = useState('')
  const [category, setCategory] = useState<MemoryCategory>('fact')
  const [pinned, setPinned] = useState(false)
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [managing, setManaging] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirmTargets, setConfirmTargets] = useState<string[] | null>(null)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['memories'] })
    queryClient.invalidateQueries({ queryKey: ['memory-stats'] })
  }

  const addMutation = useMutation({
    mutationFn: () =>
      apiPost<Memory>('/memories', {
        text,
        category,
        pinned,
      }),
    onSuccess: () => {
      setText('')
      setCategory('fact')
      setPinned(false)
      setError('')
      invalidate()
    },
    onError: (e) => setError((e as Error).message),
  })

  const patchMutation = useMutation({
    mutationFn: (m: Memory) =>
      apiPatch<Memory>(`/memories/${m.id}`, {
        text: m.text,
        category: m.category,
        pinned: m.pinned,
      }),
    onSuccess: () => {
      setEditingId(null)
      setText('')
      setCategory('fact')
      setPinned(false)
      setError('')
      invalidate()
    },
    onError: (e) => setError((e as Error).message),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/memories/${id}`),
    onSuccess: invalidate,
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: (ids: string[]) => Promise.all(ids.map((id) => apiDelete(`/memories/${id}`))),
    onSuccess: () => {
      setSelected(new Set())
      setConfirmTargets(null)
      invalidate()
    },
  })

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const togglePin = async (m: Memory) => {
    await apiPatch<Memory>(`/memories/${m.id}`, { pinned: !m.pinned })
    invalidate()
  }

  return (
    <Layout>
      <div className="mx-auto w-full max-w-3xl flex-1 overflow-y-auto px-4 py-8">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-indigo-700/20">
            <Brain className="size-5 text-indigo-300" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-zinc-100">Memories</h1>
            <p className="mt-0.5 text-sm text-zinc-500">
              Long-term facts the assistant remembers across conversations.
            </p>
          </div>
        </div>

        {stats && stats.total > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {MEMORY_CATEGORIES.map((c) => (
              <span
                key={c}
                className={clsx(
                  'rounded-full px-2.5 py-1 text-[11px]',
                  (stats.categories[c] ?? 0) > 0
                    ? CATEGORY_COLORS[c]
                    : 'bg-zinc-800 text-zinc-500',
                )}
              >
                {c} · {stats.categories[c] ?? 0}
              </span>
            ))}
          </div>
        )}

        <div className="mt-6 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
          <h2 className="text-sm font-medium text-zinc-100">
            {editingId ? 'Edit memory' : 'Add a memory'}
          </h2>
          <p className="mt-1 text-xs text-zinc-500">
            Tip: you can also say &quot;remember: my coffee order&quot; in chat, and the
            assistant saves facts automatically.
          </p>

          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="mb-1.5 block text-xs text-zinc-400">Memory</span>
              <Textarea
                rows={2}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="e.g. Alice prefers dark roast coffee with oat milk"
              />
            </label>

            <div className="flex flex-wrap items-center gap-3">
              <label className="block">
                <span className="mb-1.5 block text-xs text-zinc-400">Category</span>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value as MemoryCategory)}
                  className="w-40 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-indigo-600"
                >
                  {MEMORY_CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex cursor-pointer items-center gap-2 pt-5 text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={pinned}
                  onChange={(e) => setPinned(e.target.checked)}
                  className="size-4 accent-indigo-600"
                />
                Pin (always included in context)
              </label>
            </div>

            {error && <p className="text-sm text-red-400">{error}</p>}

            <div className="flex items-center gap-2">
              {editingId ? (
                <Button
                  onClick={() => {
                    const target = (memories ?? []).find((m) => m.id === editingId)
                    if (target) void patchMutation.mutate({ ...target, text, category, pinned })
                  }}
                  loading={patchMutation.isPending}
                  disabled={!text.trim()}
                >
                  <Check className="size-4" /> Save memory
                </Button>
              ) : (
                <Button
                  onClick={() => void addMutation.mutate()}
                  loading={addMutation.isPending}
                  disabled={!text.trim()}
                >
                  <Plus className="size-4" /> Add memory
                </Button>
              )}
              <Button
                variant="ghost"
                onClick={() => {
                  setEditingId(null)
                  setText('')
                  setCategory('fact')
                  setPinned(false)
                  setError('')
                }}
              >
                Clear
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-400">
              Saved memories
              {memories ? (
                <span className="ml-2 font-normal normal-case text-zinc-500">
                  {memories.length}
                </span>
              ) : null}
            </h2>
            {memories && memories.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  setManaging((m) => !m)
                  setSelected(new Set())
                }}
                className="flex items-center gap-1.5 rounded-lg border border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-300 transition-colors hover:bg-zinc-800 hover:text-zinc-100"
              >
                {managing ? <X className="size-3.5" /> : <Pencil className="size-3.5" />}
                {managing ? 'Done' : 'Edit'}
              </button>
            )}
          </div>

          {isLoading ? (
            <p className="mt-3 flex items-center gap-2 text-sm text-zinc-500">
              <Loader2 className="size-4 animate-spin" /> Loading memories…
            </p>
          ) : (memories ?? []).length === 0 ? (
            <p className="mt-3 rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-3 text-sm text-zinc-400">
              No memories saved yet. Add one above, or tell the assistant
              &quot;remember: …&quot; in chat.
            </p>
          ) : (
            <>
              <div className="mt-3 space-y-2">
              {managing && (
                <label className="flex cursor-pointer items-center gap-2 px-1 py-1 text-xs text-zinc-400 hover:text-zinc-200">
                  <input
                    type="checkbox"
                    checked={(memories ?? []).length > 0 && selected.size === (memories ?? []).length}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked ? new Set((memories ?? []).map((m) => m.id)) : new Set(),
                      )
                    }
                    className="size-4 accent-indigo-600"
                  />
                  Select all
                </label>
              )}
              {(memories ?? []).map((m) => (
                <div
                  key={m.id}
                  className={clsx(
                    'flex items-start gap-3 rounded-xl border bg-zinc-900/60 px-4 py-3',
                    selected.has(m.id) ? 'border-indigo-600/60' : 'border-zinc-800',
                  )}
                >
                  {managing && (
                    <input
                      type="checkbox"
                      checked={selected.has(m.id)}
                      onChange={() => toggleSelect(m.id)}
                      className="mt-1 size-4 shrink-0 accent-indigo-600"
                      aria-label={`Select memory: ${m.text}`}
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-zinc-100">{m.text}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">
                      <span
                        className={clsx(
                          'rounded-full px-2 py-0.5',
                          CATEGORY_COLORS[m.category] ?? 'bg-zinc-800 text-zinc-400',
                        )}
                      >
                        {m.category}
                      </span>
                      <span className="rounded-full bg-zinc-800 px-2 py-0.5">
                        {SOURCE_LABELS[m.source]}
                      </span>
                      {m.pinned && (
                        <span className="flex items-center gap-1 text-indigo-400">
                          <Pin className="size-3" /> pinned
                        </span>
                      )}
                      <span>used {m.uses}×</span>
                      <span>
                        {new Date(m.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                  <ActionMenu
                    pinned={m.pinned}
                    onPin={() => void togglePin(m)}
                    onEdit={() => {
                      setEditingId(m.id)
                      setText(m.text)
                      setCategory(m.category)
                      setPinned(m.pinned)
                      setError('')
                      window.scrollTo({ top: 0, behavior: 'smooth' })
                    }}
                    onDelete={() => void deleteMutation.mutate(m.id)}
                  />
                </div>
              ))}
            </div>
            {managing && selected.size > 0 && (
              <div className="mt-3 flex items-center gap-3 rounded-xl border border-indigo-600/40 bg-indigo-950/40 px-4 py-3">
                <span className="text-sm text-zinc-200">{selected.size} selected</span>
                <div className="flex-1" />
                <button
                  type="button"
                  onClick={() => {
                    const ids = [...selected]
                    if (ids.length > 1) setConfirmTargets(ids)
                    else if (ids.length === 1) void bulkDeleteMutation.mutate(ids)
                  }}
                  className="flex items-center gap-2 rounded-lg bg-red-600/90 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-red-600"
                >
                  <Trash2 className="size-3.5" /> Delete selected
                </button>
              </div>
            )}
            </>
          )}
        </div>

      <ConfirmDialog
        open={confirmTargets !== null && confirmTargets.length > 1}
        title="Delete memories"
        message={`This will permanently delete ${confirmTargets?.length ?? 0} memories.`}
        confirmLabel={bulkDeleteMutation.isPending ? 'Deleting…' : 'Delete'}
        loading={bulkDeleteMutation.isPending}
        onCancel={() => setConfirmTargets(null)}
        onConfirm={() => {
          if (confirmTargets) void bulkDeleteMutation.mutate(confirmTargets)
        }}
      />
      </div>
    </Layout>
  )
}