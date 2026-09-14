import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownUp, Check, FlaskConical, Save } from 'lucide-react'
import { apiFetch, apiPatch, apiPost } from '../../api/client'
import type { RerankerConfig, RerankerTestResult } from '../../api/types'
import { Button, Input } from '../ui'

export function RerankerSettings() {
  const queryClient = useQueryClient()
  const { data: config } = useQuery({
    queryKey: ['reranker-config'],
    queryFn: () => apiFetch<RerankerConfig>('/reranker/config'),
  })

  const [url, setUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<RerankerTestResult | null>(null)
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
      const res = await apiPost<RerankerTestResult>('/reranker/test', {
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
      await apiPatch<RerankerConfig>('/reranker/config', {
        url,
        model,
        api_key: apiKey,
      })
      setApiKey('')
      await queryClient.invalidateQueries({ queryKey: ['reranker-config'] })
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
        <ArrowDownUp className="size-4 text-indigo-400" />
        Reranker (memory ranking)
      </h2>
      <p className="mt-1 text-xs text-zinc-500">
        When memory candidates exceed the retrieval limit, they are ranked by fused
        relevance score. Set a remote reranker endpoint (Jina/Cohere-style{' '}
        <code className="rounded bg-zinc-800 px-1 py-0.5">/rerank</code> API) to
        reorder candidates by cross-encoder relevance. Leave empty for fused-score
        ranking only.
      </p>

      <div className="mt-4 space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-xs text-zinc-400">Reranker URL</span>
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://api.jina.ai/v1/rerank (optional)"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs text-zinc-400">Model</span>
            <Input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="jina-reranker-v2-base-multilingual"
            />
          </label>
        </div>

        <label className="block">
          <span className="mb-1.5 block text-xs text-zinc-400">API key (if required)</span>
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={config?.has_api_key ? '•••••••• (saved)' : 'None'}
          />
        </label>

        {error && <p className="text-sm text-red-400">{error}</p>}

        {testResult && (
          <div
            className={`rounded-lg border px-3 py-2 text-sm ${
              testResult.ok
                ? 'border-indigo-600/30 bg-indigo-600/10 text-indigo-300'
                : 'border-red-500/30 bg-red-500/10 text-red-300'
            }`}
          >
            {testResult.message}
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
