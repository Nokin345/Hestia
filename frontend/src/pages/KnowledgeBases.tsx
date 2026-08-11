import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Check, Edit3, FileText, Link as LinkIcon, Loader2, Trash2, UploadCloud, X } from 'lucide-react'
import { clsx } from 'clsx'
import { apiDelete, apiFetch, apiPatch, apiPost } from '../api/client'
import type { KbDocument, KbListResult } from '../api/types'
import { Layout } from '../components/layout/Layout'
import { Button, ConfirmDialog } from '../components/ui'

const ACCEPT = '.txt,.md,.csv,.pdf,.json,.xml'

export default function KnowledgeBasesPage() {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [editing, setEditing] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  const [busy, setBusy] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['kb'],
    queryFn: () => apiFetch<KbListResult>('/kb'),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['kb'] })
  const docs = data?.documents ?? []

  const handleFiles = async (files: FileList | null) => {
    if (!files || !files.length) return
    setError('')
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const form = new FormData()
        form.append('file', file)
        const res = await fetch('/api/kb', {
          method: 'POST',
          credentials: 'include',
          body: form,
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error((body as { detail?: string }).detail || `HTTP ${res.status}`)
        }
      }
      invalidate()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/kb/${id}`),
    onSuccess: invalidate,
  })

  const toggleDoc = async (d: KbDocument) => {
    setBusy(true)
    try {
      await apiPatch(`/kb/${d.id}?enabled=${!d.enabled}`)
      invalidate()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const exitEdit = () => {
    setEditing(false)
    setSelected(new Set())
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
    setSelected(new Set(docs.map((d) => d.id)))
  }
  const selectNone = () => setSelected(new Set())

  const bulk = async (action: 'enable' | 'disable' | 'delete') => {
    const ids = Array.from(selected)
    if (!ids.length) return
    setBusy(true)
    setError('')
    try {
      if (action === 'delete') {
        setConfirmBulkDelete(false)
      }
      await apiPost(`/kb/bulk`, { ids, action })
      invalidate()
      setSelected(new Set())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Layout>
      <div className="mx-auto w-full max-w-3xl flex-1 overflow-y-auto px-4 py-8">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-indigo-700/20">
            <BookOpen className="size-5 text-indigo-300" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-zinc-100">Knowledge Bases</h1>
            <p className="mt-0.5 text-sm text-zinc-500">
              Your private document store. Toggle the book icon in the chat composer to
              ground answers in these documents (RAG).
            </p>
          </div>
        </div>

        {data && (
          <div className="mt-4 flex flex-wrap gap-2">
            <span
              className={`rounded-full px-2.5 py-1 text-[11px] ${
                data.healthy
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : 'bg-red-500/15 text-red-300'
              }`}
            >
              {data.healthy ? 'Embedding ready' : 'Embedding unavailable'}
            </span>
            <span className="rounded-full bg-zinc-800 px-2.5 py-1 text-[11px] text-zinc-400">
              {data.stats?.count ?? 0} chunks indexed
            </span>
            <span className="rounded-full bg-zinc-800 px-2.5 py-1 text-[11px] text-zinc-400">
              {docs.length} document{docs.length === 1 ? '' : 's'}
            </span>
          </div>
        )}

        <div className="mt-6 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
          <h2 className="text-sm font-medium text-zinc-100">Add documents</h2>
          <p className="mt-1 text-xs text-zinc-500">
            PDF, TXT, Markdown, CSV, JSON and XML. Files are chunked and embedded so they
            can be retrieved during chat when the Knowledge Base toggle is on.
          </p>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPT}
            onChange={(e) => void handleFiles(e.target.files)}
            className="hidden"
          />
          <div className="mt-4 flex items-center gap-2">
            <Button onClick={() => fileInputRef.current?.click()} loading={uploading} variant="outline">
              {uploading ? null : <UploadCloud className="size-4" />} Upload documents
            </Button>
          </div>
          {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
        </div>

        <div className="mt-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-400">
              Indexed documents
              {docs.length ? <span className="ml-2 font-normal normal-case text-zinc-500">{docs.length}</span> : null}
            </h2>
            {docs.length > 0 && (
              <button
                type="button"
                onClick={() => (editing ? exitEdit() : setEditing(true))}
                className={clsx(
                  'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  editing
                    ? 'bg-indigo-600/15 text-indigo-300'
                    : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200',
                )}
              >
                {editing ? <X className="size-3.5" /> : <Edit3 className="size-3.5" />}
                {editing ? 'Done' : 'Edit'}
              </button>
            )}
          </div>

          {editing && (
            <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2">
              <span className="text-xs text-zinc-400">
                {selected.size} selected
              </span>
              <button
                type="button"
                onClick={selected.size === docs.length ? selectNone : selectAll}
                className="rounded-md px-2 py-0.5 text-xs text-indigo-400 transition-colors hover:bg-indigo-600/10"
              >
                {selected.size === docs.length ? 'Select none' : 'Select all'}
              </button>
              <div className="ml-auto flex items-center gap-1.5">
                <Button variant="outline" size="sm" disabled={!selected.size || busy} onClick={() => void bulk('enable')}>
                  <Check className="size-3.5" /> Enable
                </Button>
                <Button variant="outline" size="sm" disabled={!selected.size || busy} onClick={() => void bulk('disable')}>
                  <X className="size-3.5" /> Disable
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={!selected.size || busy}
                  onClick={() => setConfirmBulkDelete(true)}
                >
                  <Trash2 className="size-3.5" /> Delete
                </Button>
              </div>
            </div>
          )}

          {isLoading ? (
            <p className="mt-3 flex items-center gap-2 text-sm text-zinc-500">
              <Loader2 className="size-4 animate-spin" /> Loading documents…
            </p>
          ) : docs.length === 0 ? (
            <p className="mt-3 rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-3 text-sm text-zinc-400">
              No documents indexed yet. Upload your first PDF or text file above.
            </p>
          ) : (
            <div className="mt-3 space-y-2">
              {docs.map((d) => (
                <div
                  key={d.id}
                  className={clsx(
                    'flex items-start gap-3 rounded-xl border px-4 py-3',
                    d.enabled
                      ? 'border-zinc-800 bg-zinc-900/60'
                      : 'border-zinc-800/50 bg-zinc-900/30 opacity-60',
                  )}
                >
                  {editing && (
                    <button
                      type="button"
                      onClick={() => toggleSelect(d.id)}
                      className={clsx(
                        'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border transition-colors',
                        selected.has(d.id)
                          ? 'border-indigo-600 bg-indigo-600 text-white'
                          : 'border-zinc-600 text-transparent hover:border-zinc-400',
                      )}
                      aria-checked={selected.has(d.id)}
                      role="checkbox"
                    >
                      <Check className="size-3.5" />
                    </button>
                  )}
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-indigo-700/10">
                    <FileText className="size-4 text-indigo-300" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-zinc-100">{d.filename}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">
                      <span className="rounded-full bg-zinc-800 px-2 py-0.5">{d.mime}</span>
                      <span>{d.chunk_count} chunks</span>
                      <span>{new Date(d.created_at).toLocaleDateString()}</span>
                      {!d.enabled && (
                        <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-zinc-500">
                          disabled
                        </span>
                      )}
                      {d.preview && (
                        <span className="truncate max-w-64 text-zinc-500">{d.preview}…</span>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={d.enabled}
                      disabled={busy}
                      onClick={() => void toggleDoc(d)}
                      title={d.enabled ? 'Enabled — used by RAG. Click to disable.' : 'Disabled — not used by RAG. Click to enable.'}
                      className={clsx(
                        'flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors',
                        d.enabled ? 'bg-emerald-600 justify-end' : 'bg-zinc-700 justify-start',
                      )}
                    >
                      <span className="size-4 rounded-full bg-white shadow" />
                    </button>
                    <a
                      href={d.url}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
                      title="Open file"
                    >
                      <LinkIcon className="size-4" />
                    </a>
                    <button
                      onClick={() => void deleteMutation.mutate(d.id)}
                      className="rounded-lg p-2 text-zinc-400 hover:bg-red-500/10 hover:text-red-400"
                      title="Delete from knowledge base"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {confirmBulkDelete && (
        <ConfirmDialog
          open
          title={`Delete ${selected.size} document${selected.size === 1 ? '' : 's'}?`}
          message={`This removes the selected document${selected.size === 1 ? '' : 's'} and its indexed chunks from the knowledge base.`}
          confirmLabel="Delete"
          onConfirm={() => void bulk('delete')}
          onCancel={() => setConfirmBulkDelete(false)}
        />
      )}
    </Layout>
  )
}