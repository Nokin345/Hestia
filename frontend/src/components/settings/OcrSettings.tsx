import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, FlaskConical, ScanText, Save, Upload } from 'lucide-react'
import { apiFetch, apiPatch } from '../../api/client'
import type { OcrConfig, OcrTestResult } from '../../api/types'
import { Button, Input } from '../ui'

function BackendBadge({ result }: { result: OcrTestResult }) {
  const styles: Record<string, string> = {
    remote: 'bg-emerald-600/15 text-emerald-400',
    local: 'bg-amber-500/15 text-amber-400',
    none: 'bg-red-500/15 text-red-400',
  }
  const label =
    result.backend === 'remote'
      ? 'Remote OCR'
      : result.backend === 'local'
        ? 'Local fallback'
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

export function OcrSettings() {
  const queryClient = useQueryClient()
  const { data: config } = useQuery({
    queryKey: ['ocr-config'],
    queryFn: () => apiFetch<OcrConfig>('/ocr/config'),
  })

  const [url, setUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [testImage, setTestImage] = useState<File | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<OcrTestResult | null>(null)
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
      const form = new FormData()
      form.append('url', url)
      form.append('model', model)
      if (apiKey) form.append('api_key', apiKey)
      if (testImage) form.append('file', testImage)
      const res = await fetch(`/api/ocr/test`, {
        method: 'POST',
        credentials: 'include',
        body: form,
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`)
      setTestResult((await res.json()) as OcrTestResult)
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
      await apiPatch<OcrConfig>('/ocr/config', {
        url,
        model,
        api_key: apiKey,
      })
      setApiKey('')
      await queryClient.invalidateQueries({ queryKey: ['ocr-config'] })
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
        <ScanText className="size-4 text-indigo-400" />
        OCR (scanned documents)
      </h2>
      <p className="mt-1 text-xs text-zinc-500">
        Image-based PDFs (scans, photos) have no text layer, so their text must be read
        by an OCR backend. By default a local{' '}
        <code className="rounded bg-zinc-800 px-1 py-0.5">RapidOCR</code> model runs on CPU
        (multilingual, ~ONNX). Leave URL empty for local; set it to an OpenAI-compatible{' '}
        <code>/v1/chat/completions</code> vision endpoint (llama.cpp, vLLM, Ollama — e.g.
        NuExtract3, Qwen-VL) to use a remote model.
      </p>

      <div className="mt-4 space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-xs text-zinc-400">Remote OCR URL</span>
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://host:port/v1 (optional)"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs text-zinc-400">Model</span>
            <Input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="numind/NuExtract3"
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

        <label className="block">
          <span className="mb-1.5 block text-xs text-zinc-400">
            Test file (optional) — an image or PDF to verify extraction
          </span>
          <div className="flex items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept="image/*,.pdf"
              className="hidden"
              onChange={(e) => setTestImage(e.target.files?.[0] ?? null)}
            />
            <Button variant="outline" type="button" onClick={() => fileRef.current?.click()}>
              <Upload className="size-4" />
              {testImage ? testImage.name : 'Choose image or PDF'}
            </Button>
            {testImage && (
              <button
                type="button"
                onClick={() => setTestImage(null)}
                className="text-xs text-zinc-500 hover:text-zinc-300"
              >
                clear
              </button>
            )}
          </div>
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
            <div className="flex items-center gap-2">
              <span className="font-medium">Backend:</span>
              <BackendBadge result={testResult} />
              <span className="text-zinc-400">—</span>
              <span>{testResult.message}</span>
            </div>
            {testResult.model && (
              <p className="mt-1 text-xs text-zinc-400">
                model {testResult.model}
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
