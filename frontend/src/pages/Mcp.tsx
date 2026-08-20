import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, FlaskConical, PlugZap, Plus, Save, Trash2, X } from 'lucide-react'
import { clsx } from 'clsx'
import { apiDelete, apiFetch, apiPatch, apiPost } from '../api/client'
import type { McpHeader, McpServer, McpServerTestResult } from '../api/types'
import { Layout } from '../components/layout/Layout'
import { Button, ConfirmDialog, Input } from '../components/ui'

const EMPTY_FORM = {
  name: '',
  transport: 'http' as 'http' | 'sse',
  url: '',
  auth_token: '',
  headers: [] as McpHeader[],
}

function TransportBadge({ transport }: { transport: string }) {
  return (
    <span
      className={clsx(
        'rounded-full px-2 py-0.5 text-[11px] font-medium',
        transport === 'sse'
          ? 'bg-amber-500/15 text-amber-400'
          : 'bg-indigo-600/15 text-indigo-400',
      )}
    >
      {transport === 'sse' ? 'SSE' : 'HTTP'}
    </span>
  )
}

function ToolList({ result }: { result: McpServerTestResult }) {
  if (!result.tools.length) return null
  return (
    <div className="mt-3 space-y-1.5">
      {result.tools.map((t) => (
        <div key={t.name} className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-2.5 py-2">
          <div className="flex items-center gap-2">
            <code className="text-xs text-emerald-300">{t.name}</code>
            {t.server && (
              <span className="rounded bg-emerald-500/15 px-1 py-px text-[10px] font-medium text-emerald-400">
                {t.server}
              </span>
            )}
          </div>
          {t.description && (
            <p className="mt-0.5 text-[11px] leading-snug text-zinc-500">{t.description}</p>
          )}
        </div>
      ))}
    </div>
  )
}

export function McpPage() {
  const queryClient = useQueryClient()
  const { data: servers } = useQuery({
    queryKey: ['mcp-servers'],
    queryFn: () => apiFetch<McpServer[]>('/mcp/servers'),
  })

  const [form, setForm] = useState(EMPTY_FORM)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [testResult, setTestResult] = useState<McpServerTestResult | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<McpServer | null>(null)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (notice) {
      const t = setTimeout(() => setNotice(''), 2500)
      return () => clearTimeout(t)
    }
  }, [notice])

  const patch = (next: Partial<typeof form>) => setForm((f) => ({ ...f, ...next }))
  const setHeader = (i: number, key: 'key' | 'value', value: string) =>
    setForm((f) => ({
      ...f,
      headers: f.headers.map((h, j) => (j === i ? { ...h, [key]: value } : h)),
    }))

  const startEdit = (s: McpServer) => {
    setEditingId(s.id)
    setTestResult(null)
    setError('')
    setForm({
      name: s.name,
      transport: s.transport,
      url: s.url,
      auth_token: s.auth_token,
      headers: s.headers,
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const resetForm = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setTestResult(null)
    setError('')
  }

  const test = async () => {
    if (!form.url.trim()) return
    setTesting(true)
    setError('')
    setTestResult(null)
    try {
      const body = {
        transport: form.transport,
        url: form.url,
        auth_token: form.auth_token,
        headers: form.headers,
      }
      const res = editingId
        ? await apiPost<McpServerTestResult>(`/mcp/servers/${editingId}/test`)
        : await apiPost<McpServerTestResult>('/mcp/test', body)
      setTestResult(res)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setTesting(false)
    }
  }

  const save = async () => {
    const name = form.name.trim()
    if (!name || !form.url.trim()) {
      setError('Name and URL are required.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const body = {
        name,
        transport: form.transport,
        url: form.url,
        auth_token: form.auth_token,
        headers: form.headers,
      }
      if (editingId) {
        await apiPatch<McpServer>(`/mcp/servers/${editingId}`, body)
      } else {
        await apiPost<McpServer>('/mcp/servers', body)
      }
      await queryClient.invalidateQueries({ queryKey: ['mcp-servers'] })
      await queryClient.invalidateQueries({ queryKey: ['mcp-all-tools'] })
      setNotice(editingId ? 'Server updated.' : 'Server added.')
      resetForm()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async (s: McpServer) => {
    try {
      await apiDelete(`/mcp/servers/${s.id}`)
      await queryClient.invalidateQueries({ queryKey: ['mcp-servers'] })
      await queryClient.invalidateQueries({ queryKey: ['mcp-all-tools'] })
      setConfirmDelete(null)
    } catch (e) {
      setError((e as Error).message)
      setConfirmDelete(null)
    }
  }

  const toggleEnabled = async (s: McpServer) => {
    try {
      await apiPatch<McpServer>(`/mcp/servers/${s.id}`, { enabled: !s.enabled })
      await queryClient.invalidateQueries({ queryKey: ['mcp-servers'] })
      await queryClient.invalidateQueries({ queryKey: ['mcp-all-tools'] })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <Layout>
      <div className="mx-auto w-full max-w-3xl flex-1 overflow-y-auto px-4 py-6">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-indigo-700/20">
            <PlugZap className="size-5 text-indigo-300" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-zinc-100">MCP Servers</h1>
            <p className="mt-0.5 text-sm text-zinc-500">
              Connect Model Context Protocol servers to give the assistant access to external tools.
              Their tools appear in chat prefixed with the server name.
            </p>
          </div>
        </div>

        {notice && <p className="mt-3 text-sm text-emerald-400">{notice}</p>}
        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

        {/* Server list */}
        <div className="mt-6 space-y-2">
          {servers && servers.length === 0 && (
            <div className="rounded-lg border border-dashed border-zinc-700 px-4 py-6 text-center text-sm text-zinc-600">
              No MCP servers configured yet. Add one below.
            </div>
          )}
          {servers?.map((s) => (
            <div
              key={s.id}
              className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-zinc-100">{s.name}</span>
                  <TransportBadge transport={s.transport} />
                </div>
                <p className="truncate text-xs text-zinc-500">{s.url}</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={s.enabled}
                onClick={() => toggleEnabled(s)}
                title={s.enabled ? 'Enabled — click to disable' : 'Disabled — click to enable'}
                className={clsx(
                  'flex h-6 w-11 shrink-0 items-center rounded-full px-0.5 transition-colors',
                  s.enabled ? 'bg-emerald-600 justify-end' : 'bg-zinc-700 justify-start',
                )}
              >
                <span className="size-5 rounded-full bg-white shadow" />
              </button>
              <button
                type="button"
                onClick={() => startEdit(s)}
                className="rounded-md px-2 py-1 text-xs text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
              >
                Edit
              </button>
              <button
                type="button"
                onClick={() => setConfirmDelete(s)}
                className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-red-500/10 hover:text-red-400"
                title="Delete server"
              >
                <Trash2 className="size-4" />
              </button>
            </div>
          ))}
        </div>

        {/* Add / edit form */}
        <div className="mt-6 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-zinc-100">
              {editingId ? `Edit ${servers?.find((s) => s.id === editingId)?.name ?? 'server'}` : 'Add server'}
            </h2>
            {editingId && (
              <button
                type="button"
                onClick={resetForm}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
              >
                <X className="size-3" /> Cancel
              </button>
            )}
          </div>

          <div className="mt-4 space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-xs text-zinc-400">Name</span>
                <Input
                  value={form.name}
                  onChange={(e) => patch({ name: e.target.value })}
                  placeholder="e.g. filesystem"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-xs text-zinc-400">Transport</span>
                <select
                  value={form.transport}
                  onChange={(e) =>
                    patch({ transport: e.target.value as 'http' | 'sse' })
                  }
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none transition-colors focus:border-indigo-600 focus:ring-2 focus:ring-indigo-600/30"
                >
                  <option value="http">Streamable HTTP</option>
                  <option value="sse">SSE</option>
                </select>
              </label>
            </div>

            <label className="block">
              <span className="mb-1.5 block text-xs text-zinc-400">URL</span>
              <Input
                value={form.url}
                onChange={(e) => patch({ url: e.target.value })}
                placeholder="https://example.com/mcp"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs text-zinc-400">
                Bearer token <span className="text-zinc-600">(optional)</span>
              </span>
              <Input
                type="password"
                value={form.auth_token}
                onChange={(e) => patch({ auth_token: e.target.value })}
                placeholder="Authorization: Bearer …"
              />
            </label>

            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-xs text-zinc-400">Custom headers</span>
                <button
                  type="button"
                  onClick={() => patch({ headers: [...form.headers, { key: '', value: '' }] })}
                  className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-indigo-400 transition-colors hover:bg-indigo-600/10"
                >
                  <Plus className="size-3" /> Add header
                </button>
              </div>
              {form.headers.length === 0 && (
                <p className="text-[11px] text-zinc-600">None.</p>
              )}
              <div className="space-y-1.5">
                {form.headers.map((h, i) => (
                  <div key={i} className="flex items-center gap-1.5">
                    <Input
                      value={h.key}
                      onChange={(e) => setHeader(i, 'key', e.target.value)}
                      placeholder="Header"
                      className="w-40"
                    />
                    <Input
                      value={h.value}
                      onChange={(e) => setHeader(i, 'value', e.target.value)}
                      placeholder="Value"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        patch({ headers: form.headers.filter((_, j) => j !== i) })
                      }
                      className="shrink-0 rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-red-500/10 hover:text-red-400"
                    >
                      <X className="size-4" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {testResult && (
            <div
              className={clsx(
                'mt-4 rounded-lg border px-3 py-2 text-sm',
                testResult.ok
                  ? 'border-indigo-600/30 bg-indigo-600/10 text-indigo-300'
                  : 'border-red-500/30 bg-red-500/10 text-red-300',
              )}
            >
              <span>{testResult.message}</span>
              <ToolList result={testResult} />
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => void test()} loading={testing}>
              <FlaskConical className="size-4" /> Test
            </Button>
            <Button onClick={() => void save()} loading={saving}>
              {editingId ? <Save className="size-4" /> : <Check className="size-4" />}
              {editingId ? 'Save changes' : 'Add server'}
            </Button>
          </div>
        </div>
      </div>

      {confirmDelete && (
        <ConfirmDialog
          open
          title="Delete MCP server?"
          message={`This removes "${confirmDelete.name}" and disconnects its tools.`}
          confirmLabel="Delete"
          onConfirm={() => void remove(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </Layout>
  )
}
