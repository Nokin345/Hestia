import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, FlaskConical, Save } from 'lucide-react'
import { apiFetch, apiPatch, apiPost } from '../../api/client'
import type { EmbeddingConfig, EmbeddingStats, EmbeddingTestResult } from '../../api/types'
import { Button, Input } from '../ui'

function BackendBadge({ result }: { result: EmbeddingTestResult }) {
  const styles: Record<string, string> = {
    remote: 'bg-indigo-600/15 text-indigo-400',
    local: result.fallback
      ? 'bg-amber-500/15 text-amber-400'
      : 'bg-emerald-600/15 text-emerald-400',
    none: 'bg-red-500/15 text-red-400',
  }
  const label =
    result.backend === 'remote'
      ? 'Remote embedding'
      : result.backend === 'local'
        ? result.fallback
          ? 'Local fallback'
          : 'Local (CPU)'
        : 'none'
  return (
    <span
      className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ${
        styles[result.backend] ?? styles.none
      }`}
    >
      {label}
    </span>
  )
}

export function EmbeddingSettings() {
  const queryClient = useQueryClient()
  const { data: config } = useQuery({
    queryKey: ['embedding-config'],
    queryFn: () => apiFetch<EmbeddingConfig>('/embeddings/config'),
  })
  const { data: stats } = useQuery({
    queryKey: ['embedding-stats'],
    queryFn: () => apiFetch<EmbeddingStats>('/embeddings/stats'),
  })

  const [url, setUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<EmbeddingTestResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!config) return
    setUrl(config.url)
    setModel(config.model)
  }, [config])

  const dirty =
    config !== undefined &&
    (url !== config.url || model !== config.model || apiKey !== '')

  const test = async () => {
    setTesting(true)
    setError('')
    setTestResult(null)
    try {
      const res = await apiPost<EmbeddingTestResult>('/embeddings/test', {
        enabled: true,
        url,
        model,
        api_key: apiKey,
      })
      setTestResult(res)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setTesting(false)
    }
  }

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      await apiPatch<EmbeddingConfig>('/embeddings/config', {
        enabled: true,
        url,
        model,
        api_key: apiKey,
      })
      setApiKey('')
      await queryClient.invalidateQueries({ queryKey: ['embedding-config'] })
      await queryClient.invalidateQueries({ queryKey: ['embedding-stats'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-8 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
      <h2 className="flex items-center gap-2 text-sm font-medium text-zinc-100">
        <svg
          className="size-4 text-indigo-400"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M12 3v18M3 12h18" />
          <circle cx="12" cy="12" r="9" />
        </svg>
        Memory embeddings
      </h2>
      <p className="mt-1 text-xs text-zinc-500">
        Semantic search over memories uses an embedding model. By default a local{' '}
        <code className="rounded bg-zinc-800 px-1 py-0.5">sentence-transformers/all-MiniLM-L6-v2</code>{' '}
        model (fastembed) is used. Leave URL empty for local; set it to an OpenAI-compatible{' '}
        <code>/v1/embeddings</code> endpoint (llama.cpp, vLLM, Ollama) to use a remote server.
        If embeddings are unavailable, retrieval falls back to keyword matching.
      </p>

      <div className="mt-4 space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-xs text-zinc-400">Remote embeddings URL</span>
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://host:port/v1/embeddings (optional)"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs text-zinc-400">Model</span>
            <Input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="all-MiniLM-L6-v2"
            />
          </label>
        </div>

        <label className="block">
          <span className="mb-1.5 block text-xs text-zinc-400">API key (remote only)</span>
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={config?.has_api_key ? '•••••••• (saved)' : 'None'}
          />
        </label>

        {stats && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3 text-xs text-zinc-400">
            {stats.healthy ? (
              <span className="flex items-center gap-2">
                <Check className="size-3.5 text-emerald-400" />
                {stats.count} vector{stats.count === 1 ? '' : 's'} indexed via {stats.lane} (
                {stats.model}, dim {stats.dimension})
              </span>
            ) : (
              <span>
                Vector store not healthy — semantic search disabled. Check the embedding backend or
                the volume path for ChromaDB storage.
              </span>
            )}
            {url.trim() && stats?.lane === 'fastembed' && (
              <span className="mt-1 block text-zinc-500">
                Remote endpoint configured but unreachable or not enabled — using local fastembed
                (CPU).
              </span>
            )}
          </div>
        )}

        {error && <p className="text-sm text-red-400">{error}</p>}

        {testResult && (
          <div
            className={`rounded-lg border px-3 py-2 text-sm ${
              testResult.ok
                ? 'border-indigo-600/30 bg-indigo-600/10 text-indigo-300'
                : 'border-red-500/30 bg-red-500/10 text-red-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <span className="font-medium">Backend:</span>
              <BackendBadge result={testResult} />
              <span className="text-zinc-400">—</span>
              <span>{testResult.message}</span>
            </div>
            {testResult.dimension != null && (
              <p className="mt-1 text-xs text-zinc-400">
                model {testResult.model}, dim {testResult.dimension}
              </p>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => void test()} loading={testing}>
            <FlaskConical className="size-4" /> Test
          </Button>
          <Button onClick={() => void save()} loading={saving} disabled={!dirty}>
            {saved ? <Check className="size-4" /> : <Save className="size-4" />}
            {saved ? 'Saved' : 'Save'}
          </Button>
        </div>
      </div>
    </div>
  )
}