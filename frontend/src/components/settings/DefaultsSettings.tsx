import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookmarkPlus, BookOpen, Check, Code2, Database, Globe, Save, Trash2 } from 'lucide-react'
import { apiDelete, apiFetch, apiPatch, apiPost } from '../../api/client'
import type { DefaultsConfig, SystemPromptPreset } from '../../api/types'
import { Button, Input, Textarea } from '../ui'

function Toggle({
  checked,
  onChange,
  label,
  description,
  icon,
  color,
}: {
  checked: boolean
  onChange: () => void
  label: string
  description: string
  icon: React.ReactNode
  color: string
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
      <div className="min-w-0 flex-1">
        <span className="flex items-center gap-2.5 text-sm text-zinc-300">
          <span className={color}>{icon}</span> {label}
        </span>
        <p className="mt-0.5 pl-[26px] text-xs text-zinc-500">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={onChange}
        className={`flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors ${
          checked ? 'justify-end bg-indigo-600' : 'justify-start bg-zinc-700'
        }`}
      >
        <span className="size-4 rounded-full bg-white shadow" />
      </button>
    </div>
  )
}

export function DefaultsSettings() {
  const queryClient = useQueryClient()
  const { data: config } = useQuery({
    queryKey: ['defaults'],
    queryFn: () => apiFetch<DefaultsConfig>('/defaults'),
  })
  const { data: presets } = useQuery({
    queryKey: ['presets'],
    queryFn: () => apiFetch<SystemPromptPreset[]>('/defaults/presets'),
  })

  const [systemPrompt, setSystemPrompt] = useState('')
  const [kb, setKb] = useState(false)
  const [memory, setMemory] = useState(false)
  const [search, setSearch] = useState(false)
  const [code, setCode] = useState(false)
  const [presetName, setPresetName] = useState('')
  const [savingPrompt, setSavingPrompt] = useState(false)
  const [savingPreset, setSavingPreset] = useState(false)
  const [savingTools, setSavingTools] = useState(false)
  const [promptSaved, setPromptSaved] = useState(false)
  const [presetSaved, setPresetSaved] = useState(false)
  const [toolsSaved, setToolsSaved] = useState(false)
  const [promptError, setPromptError] = useState('')
  const [toolsError, setToolsError] = useState('')

  const appliedPrompt =
    config?.default_system_prompt?.trim() ||
    presets?.find((p) => p.name === 'default')?.content ||
    ''

  useEffect(() => {
    if (!config) return
    setSystemPrompt(appliedPrompt)
    setKb(config.default_kb_enabled)
    setMemory(config.default_memory_enabled)
    setSearch(config.default_search_enabled)
    setCode(config.default_code_enabled)
  }, [config, presets, appliedPrompt])

  const promptDirty = systemPrompt !== appliedPrompt

  const toolsDirty =
    config !== undefined &&
    (kb !== config.default_kb_enabled ||
      memory !== config.default_memory_enabled ||
      search !== config.default_search_enabled ||
      code !== config.default_code_enabled)

  const savePrompt = async () => {
    setSavingPrompt(true)
    setPromptError('')
    try {
      await apiPatch<DefaultsConfig>('/defaults', {
        default_system_prompt: systemPrompt,
      })
      await queryClient.invalidateQueries({ queryKey: ['defaults'] })
      setPromptSaved(true)
      setTimeout(() => setPromptSaved(false), 2000)
    } catch (e) {
      setPromptError((e as Error).message)
    } finally {
      setSavingPrompt(false)
    }
  }

  const saveTools = async () => {
    setSavingTools(true)
    setToolsError('')
    try {
      await apiPatch<DefaultsConfig>('/defaults', {
        default_kb_enabled: kb,
        default_memory_enabled: memory,
        default_search_enabled: search,
        default_code_enabled: code,
      })
      await queryClient.invalidateQueries({ queryKey: ['defaults'] })
      setToolsSaved(true)
      setTimeout(() => setToolsSaved(false), 2000)
    } catch (e) {
      setToolsError((e as Error).message)
    } finally {
      setSavingTools(false)
    }
  }

  const saveAsPreset = async () => {
    const name = presetName.trim()
    if (!name || !systemPrompt.trim()) return
    setSavingPreset(true)
    setPromptError('')
    try {
      await apiPost<SystemPromptPreset>('/defaults/presets', {
        name,
        content: systemPrompt,
      })
      setPresetName('')
      setPresetSaved(true)
      setTimeout(() => setPresetSaved(false), 2000)
      await queryClient.invalidateQueries({ queryKey: ['presets'] })
    } catch (e) {
      setPromptError((e as Error).message)
    } finally {
      setSavingPreset(false)
    }
  }

  const deletePreset = async (id: string) => {
    setPromptError('')
    try {
      await apiDelete(`/defaults/presets/${id}`)
      await queryClient.invalidateQueries({ queryKey: ['presets'] })
    } catch (e) {
      setPromptError((e as Error).message)
    }
  }

  const applyPreset = (p: SystemPromptPreset) => {
    setSystemPrompt(p.content)
    setPromptSaved(false)
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
        <h2 className="text-sm font-medium text-zinc-100">System prompt</h2>
        <p className="mt-1 text-xs text-zinc-500">
          Default system prompt applied to every new conversation. You can change it per
          conversation in the composer.
        </p>

        <div className="mt-4">
          <Textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="Leave empty for no system prompt"
            rows={4}
          />
        </div>

        {presets && presets.length > 0 && (
          <div className="mt-4">
            <span className="mb-1.5 block text-xs text-zinc-400">Presets</span>
            <div className="flex flex-wrap gap-1.5">
              {presets.map((p) => (
                <span
                  key={p.id}
                  className="flex items-center gap-1 rounded-full border border-zinc-700 bg-zinc-800/60 pl-2.5 pr-1.5 py-1 text-xs text-zinc-300"
                >
                  <button
                    onClick={() => applyPreset(p)}
                    className="hover:text-indigo-300"
                    title={`Apply "${p.name}"`}
                  >
                    {p.name}
                  </button>
                  <button
                    onClick={() => void deletePreset(p.id)}
                    className="rounded-full p-0.5 text-zinc-500 hover:bg-red-500/10 hover:text-red-400"
                    title="Delete preset"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Input
            value={presetName}
            onChange={(e) => setPresetName(e.target.value)}
            placeholder="Preset name…"
            className="w-48"
          />
          <Button
            variant="outline"
            onClick={() => void saveAsPreset()}
            loading={savingPreset}
            disabled={!presetName.trim() || !systemPrompt.trim()}
          >
            {presetSaved ? <Check className="size-4" /> : <BookmarkPlus className="size-4" />}
            {presetSaved ? 'Saved' : 'Save as preset'}
          </Button>
          <Button
            onClick={() => void savePrompt()}
            loading={savingPrompt}
            disabled={!promptDirty}
          >
            {promptSaved ? <Check className="size-4" /> : <Save className="size-4" />}
            {promptSaved ? 'Saved' : 'Save'}
          </Button>
        </div>

        {promptError && <p className="mt-3 text-sm text-red-400">{promptError}</p>}
      </div>

      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
        <h2 className="text-sm font-medium text-zinc-100">Tools</h2>
        <p className="mt-1 text-xs text-zinc-500">
          Starting state for every new conversation. You can still change any toggle per
          conversation in the composer.
        </p>

        <div className="mt-4 space-y-2">
          <Toggle
            checked={kb}
            onChange={() => setKb(!kb)}
            label="Knowledge base"
            description="Search your uploaded documents and answer from them."
            icon={<BookOpen className="size-4 text-emerald-400" />}
            color=""
          />
          <Toggle
            checked={memory}
            onChange={() => setMemory(!memory)}
            label="Memory"
            description="Recall past conversations and facts you told it about you."
            icon={<Database className="size-4 text-indigo-400" />}
            color=""
          />
          <Toggle
            checked={search}
            onChange={() => setSearch(!search)}
            label="Web search"
            description="Look up up-to-date information on the web before answering."
            icon={<Globe className="size-4 text-sky-400" />}
            color=""
          />
          <Toggle
            checked={code}
            onChange={() => setCode(!code)}
            label="Code runner"
            description="Run code (Python, Node.js, Go, Java) in a sandbox for calculations and tasks."
            icon={<Code2 className="size-4 text-amber-400" />}
            color=""
          />
        </div>

        <div className="mt-4 flex items-center gap-2">
          <Button onClick={() => void saveTools()} loading={savingTools} disabled={!toolsDirty}>
            {toolsSaved ? <Check className="size-4" /> : <Save className="size-4" />}
            {toolsSaved ? 'Saved' : 'Save'}
          </Button>
        </div>

        {toolsError && <p className="mt-3 text-sm text-red-400">{toolsError}</p>}
      </div>
    </div>
  )
}