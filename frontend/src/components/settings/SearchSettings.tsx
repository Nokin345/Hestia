import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, FlaskConical, Globe, Save } from 'lucide-react'
import { apiFetch, apiPatch, apiPost } from '../../api/client'
import type { SearchConfig, SearchTestResult } from '../../api/types'
import { Button, Input } from '../ui'

function EngineBadge({ engine }: { engine: string }) {
  const styles: Record<string, string> = {
    searxng: 'bg-indigo-600/15 text-indigo-400',
    duckduckgo: 'bg-amber-500/15 text-amber-400',
    none: 'bg-red-500/15 text-red-400',
  }
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${styles[engine] ?? styles.none}`}>
      {engine === 'searxng' ? 'SearXNG' : engine === 'duckduckgo' ? 'DuckDuckGo' : 'none'}
    </span>
  )
}

export function SearchSettings() {
  const queryClient = useQueryClient()
  const { data: config } = useQuery({
    queryKey: ['search-config'],
    queryFn: () => apiFetch<SearchConfig>('/search/config'),
  })

  const [searxngUrl, setSearxngUrl] = useState('')
  const [maxResults, setMaxResults] = useState(5)
  const [fallback, setFallback] = useState(true)
  const [fetchUrls, setFetchUrls] = useState(true)
  const [fetchLimit, setFetchLimit] = useState(1)
  const [maxChars, setMaxChars] = useState(4000)
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<SearchTestResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!config) return
    setSearxngUrl(config.searxng_url)
    setMaxResults(config.max_results)
    setFallback(config.fallback)
    setFetchUrls(config.fetch_urls)
    setFetchLimit(config.fetch_limit)
    setMaxChars(config.max_chars_per_url)
  }, [config])

  const dirty =
    config !== undefined &&
    (searxngUrl !== config.searxng_url ||
      maxResults !== config.max_results ||
      fallback !== config.fallback ||
      fetchUrls !== config.fetch_urls ||
      fetchLimit !== config.fetch_limit ||
      maxChars !== config.max_chars_per_url)

  const test = async () => {
    setTesting(true)
    setError('')
    setTestResult(null)
    try {
      const res = await apiPost<SearchTestResult>('/search/test', {
        searxng_url: searxngUrl,
        max_results: maxResults,
        fallback,
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
      await apiPatch<SearchConfig>('/search/config', {
        searxng_url: searxngUrl,
        max_results: maxResults,
        fallback,
        fetch_urls: fetchUrls,
        fetch_limit: fetchLimit,
        max_chars_per_url: maxChars,
      })
      await queryClient.invalidateQueries({ queryKey: ['search-config'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
      <h2 className="flex items-center gap-2 text-sm font-medium text-zinc-100">
        <Globe className="size-4 text-indigo-400" /> Search
      </h2>
      <p className="mt-1 text-xs text-zinc-500">
        Configure a SearXNG instance for web search. If it is unreachable, the app falls back to
        DuckDuckGo. Fetched page content is included as context for the model.
      </p>

      <div className="mt-4 space-y-4">
        <label className="block">
          <span className="mb-1.5 block text-xs text-zinc-400">SearXNG URL</span>
          <Input
            value={searxngUrl}
            onChange={(e) => setSearxngUrl(e.target.value)}
            placeholder="https://your-searxng-instance"
          />
        </label>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-xs text-zinc-400">Max results</span>
            <Input
              type="number"
              min={1}
              max={50}
              value={maxResults}
              onChange={(e) => setMaxResults(Number(e.target.value) || 1)}
            />
          </label>
          <label className="flex cursor-pointer items-center gap-2.5 pt-6">
            <input
              type="checkbox"
              checked={fallback}
              onChange={(e) => setFallback(e.target.checked)}
              className="size-4 accent-indigo-600"
            />
            <span className="text-sm text-zinc-300">Fall back to DuckDuckGo when SearXNG fails</span>
          </label>
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
          <label className="flex cursor-pointer items-center gap-2.5">
            <input
              type="checkbox"
              checked={fetchUrls}
              onChange={(e) => setFetchUrls(e.target.checked)}
              className="size-4 accent-indigo-600"
            />
            <span className="text-sm text-zinc-300">
              Fetch the top search result pages and include their content as context
            </span>
          </label>
          {fetchUrls && (
            <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-xs text-zinc-400">Pages to fetch</span>
                <Input
                  type="number"
                  min={1}
                  max={10}
                  value={fetchLimit}
                  onChange={(e) => setFetchLimit(Math.min(10, Math.max(1, Number(e.target.value) || 1)))}
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-xs text-zinc-400">Default max chars per page</span>
                <Input
                  type="number"
                  min={500}
                  max={50000}
                  step={500}
                  value={maxChars}
                  onChange={(e) => setMaxChars(Math.min(50000, Math.max(500, Number(e.target.value) || 500)))}
                />
              </label>
            </div>
          )}
        </div>

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
              <span className="font-medium">Engine:</span>
              <EngineBadge engine={testResult.engine} />
              <span className="text-zinc-400">—</span>
              <span>{testResult.message}</span>
            </div>
            {testResult.ok && testResult.results > 0 && (
              <p className="mt-1 text-xs text-zinc-400">
                {testResult.results} sample result{testResult.results === 1 ? '' : 's'} returned.
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
