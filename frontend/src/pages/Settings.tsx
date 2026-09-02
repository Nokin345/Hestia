import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Search, CheckSquare, Square, RefreshCw, Trash2, Pencil, Check, X, Plug, Server, KeyRound, Plus, Loader2, AlertTriangle, Save, Settings } from 'lucide-react'
import { apiDelete, apiFetch, apiPatch, apiPost } from '../api/client'
import type { DefaultsConfig, Provider, ProviderModel, ProviderTestResult, ModelEntry, ProviderTypeMeta } from '../api/types'
import { Layout } from '../components/layout/Layout'
import { Button, Input } from '../components/ui'
import { SearchSettings } from '../components/settings/SearchSettings'
import { OcrSettings } from '../components/settings/OcrSettings'
import { DefaultsSettings } from '../components/settings/DefaultsSettings'

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const { data: providers } = useQuery({
    queryKey: ['providers'],
    queryFn: () => apiFetch<Provider[]>('/providers'),
  })
  const { data: providerTypes } = useQuery({
    queryKey: ['provider-types'],
    queryFn: () => apiFetch<ProviderTypeMeta[]>('/providers/types'),
  })
  const { data: defaults } = useQuery({
    queryKey: ['defaults'],
    queryFn: () => apiFetch<DefaultsConfig>('/defaults'),
  })
  const { data: allModels } = useQuery({
    queryKey: ['models'],
    queryFn: () => apiFetch<ModelEntry[]>('/providers/models'),
    refetchOnWindowFocus: true,
  })

  const [defaultModel, setDefaultModel] = useState<string>('')
  const [savingDefaultModel, setSavingDefaultModel] = useState(false)
  const [defaultModelSaved, setDefaultModelSaved] = useState(false)
  const [defaultModelError, setDefaultModelError] = useState('')

  const [utilityModel, setUtilityModel] = useState<string>('')
  const [savingUtilityModel, setSavingUtilityModel] = useState(false)
  const [utilityModelSaved, setUtilityModelSaved] = useState(false)
  const [utilityModelError, setUtilityModelError] = useState('')

  useEffect(() => {
    if (defaults) setDefaultModel(defaults.default_model ?? '')
  }, [defaults])

  const defaultModelDirty =
    defaults !== undefined && (defaultModel ?? '') !== (defaults.default_model ?? '')

  useEffect(() => {
    if (defaults) setUtilityModel(defaults.utility_model ?? '')
  }, [defaults])

  const utilityModelDirty =
    defaults !== undefined && (utilityModel ?? '') !== (defaults.utility_model ?? '')

  const [type, setType] = useState('openrouter')
  const [name, setName] = useState('OpenRouter')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(providerTypes?.[0]?.default_base_url ?? '')
  const [editingId, setEditingId] = useState<string | null>(null)

  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null)
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set())
  const editingAllowedRef = useRef<ProviderModel[] | null>(null)

  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [modelsByProvider, setModelsByProvider] = useState<Record<string, ProviderModel[]>>({})
  const [loadingModels, setLoadingModels] = useState<Record<string, boolean>>({})
  const [unreachable, setUnreachable] = useState<Record<string, boolean>>({})
  const [modelSearch, setModelSearch] = useState('')
  const [formModelSearch, setFormModelSearch] = useState('')

  const [pendingAllowed, setPendingAllowed] = useState<Record<string, ProviderModel[]>>({})
  const [pendingEnabled, setPendingEnabled] = useState<Record<string, boolean>>({})
  const [applyingId, setApplyingId] = useState<string | null>(null)

  const effectiveAllowed = (p: Provider): ProviderModel[] | null =>
    p.id in pendingAllowed ? pendingAllowed[p.id] : p.allowed_models

  const effectiveEnabled = (p: Provider): boolean =>
    p.id in pendingEnabled ? pendingEnabled[p.id] : p.enabled

  const sameIdSet = (a: Set<string>, b: Set<string>) =>
    a.size === b.size && [...a].every((x) => b.has(x))

  const hasRealChanges = (p: Provider): boolean => {
    if (p.id in pendingEnabled && pendingEnabled[p.id] !== p.enabled) return true
    if (!(p.id in pendingAllowed)) return false
    const server = p.allowed_models
    const pending = pendingAllowed[p.id]
    if (server === null) {
      const models = modelsByProvider[p.id] ?? []
      const allIds = new Set(models.map((m) => m.id))
      const pendingIds = new Set(pending.map((m) => m.id))
      if (models.length > 0 && sameIdSet(pendingIds, allIds)) return false
      return true
    }
    return !sameIdSet(
      new Set(server.map((m) => m.id)),
      new Set(pending.map((m) => m.id)),
    )
  }

  const typeMeta = providerTypes?.find((t) => t.id === type)

  const resetForm = () => {
    setType('openrouter')
    setName('OpenRouter')
    setApiKey('')
    setBaseUrl(providerTypes?.[0]?.default_base_url ?? '')
    setEditingId(null)
    setFormError('')
    setTestResult(null)
    setSelectedModels(new Set())
    editingAllowedRef.current = null
  }

  const onTypeChange = (t: string) => {
    const meta = providerTypes?.find((m) => m.id === t)
    setType(t)
    if (meta) {
      setName(meta.name)
      setBaseUrl(meta.default_base_url)
    }
    setTestResult(null)
    setFormError('')
  }

  const startEdit = (p: Provider) => {
    const meta = providerTypes?.find((m) => m.id === p.type)
    setEditingId(p.id)
    setType(p.type)
    setName(p.name)
    setApiKey('')
    setBaseUrl(p.base_url ?? meta?.default_base_url ?? '')
    setTestResult(null)
    setFormError('')
    editingAllowedRef.current = p.allowed_models
    setSelectedModels(new Set())
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
  }

  const testConnection = async () => {
    setTesting(true)
    setFormError('')
    setTestResult(null)
    setFormModelSearch('')
    try {
      const res = await apiPost<ProviderTestResult>('/providers/test', {
        type,
        api_key: apiKey,
        base_url: baseUrl || undefined,
      })
      setTestResult(res)
      if (res.ok) {
        const allowed = editingAllowedRef.current
        const ids = new Set(
          allowed === null
            ? res.models.map((m) => m.id)
            : res.models.filter((m) => allowed.some((a) => a.id === m.id)).map((m) => m.id),
        )
        setSelectedModels(ids)
      }
    } catch (e) {
      setFormError((e as Error).message)
    } finally {
      setTesting(false)
    }
  }

  const toggleFormModel = (id: string) =>
    setSelectedModels((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const save = async () => {
    setSaving(true)
    setFormError('')
    try {
      const tested = testResult?.ok ?? false
      const allowedModels = tested
        ? testResult!.models.filter((m) => selectedModels.has(m.id))
        : undefined
      if (editingId) {
        const body: Record<string, unknown> = {
          name,
          api_key: apiKey,
          base_url: baseUrl || null,
        }
        if (allowedModels !== undefined) body.allowed_models = allowedModels
        await apiPatch<Provider>(`/providers/${editingId}`, body)
      } else {
        await apiPost<Provider>('/providers', {
          name,
          type,
          api_key: apiKey,
          base_url: baseUrl || null,
          allowed_models: allowedModels,
        })
      }
      await queryClient.invalidateQueries({ queryKey: ['providers'] })
      await queryClient.invalidateQueries({ queryKey: ['models'] })
      await queryClient.invalidateQueries({ queryKey: ['defaults'] })
      resetForm()
    } catch (e) {
      setFormError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async (id: string) => {
    await apiDelete(`/providers/${id}`)
    setModelsByProvider((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setUnreachable((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setPendingAllowed((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setPendingEnabled((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    await queryClient.invalidateQueries({ queryKey: ['providers'] })
    await queryClient.invalidateQueries({ queryKey: ['models'] })
    await queryClient.invalidateQueries({ queryKey: ['defaults'] })
  }

  const toggleEnabled = (p: Provider) => {
    setPendingEnabled((prev) => ({ ...prev, [p.id]: !effectiveEnabled(p) }))
  }

  const fetchModels = async (p: Provider) => {
    setLoadingModels((prev) => ({ ...prev, [p.id]: true }))
    try {
      const models = await apiFetch<ProviderModel[]>(`/providers/${p.id}/models`)
      setModelsByProvider((prev) => ({ ...prev, [p.id]: models }))
      setUnreachable((prev) => ({
        ...prev,
        [p.id]: models.some((m) => m.available === false),
      }))
    } catch {
      setModelsByProvider((prev) => ({ ...prev, [p.id]: [] }))
      setUnreachable((prev) => ({ ...prev, [p.id]: true }))
    } finally {
      setLoadingModels((prev) => ({ ...prev, [p.id]: false }))
    }
  }

  const toggleExpand = async (p: Provider) => {
    if (expandedId === p.id) {
      setExpandedId(null)
      setModelSearch('')
      return
    }
    setExpandedId(p.id)
    setModelSearch('')
    if (modelsByProvider[p.id] === undefined) await fetchModels(p)
  }

  const allowedIds = (p: Provider, models: ProviderModel[]) => {
    const eff = effectiveAllowed(p)
    if (eff === null) return new Set(models.map((m) => m.id))
    return new Set(eff.map((m) => m.id))
  }

  const toggleModel = (p: Provider, models: ProviderModel[], id: string) => {
    const eff = effectiveAllowed(p)
    const ids = allowedIds(p, models)
    if (ids.has(id)) ids.delete(id)
    else ids.add(id)
    const known = new Map<string, ProviderModel>()
    for (const m of eff === null ? [] : eff) known.set(m.id, m)
    for (const m of models) known.set(m.id, m)
    const allowed = [...ids]
      .map((mid) => known.get(mid))
      .filter((m): m is ProviderModel => Boolean(m))
    setPendingAllowed((prev) => ({ ...prev, [p.id]: allowed }))
  }

  const selectAll = (p: Provider, models: ProviderModel[]) => {
    setPendingAllowed((prev) => ({ ...prev, [p.id]: models }))
  }

  const selectNone = (p: Provider) => {
    setPendingAllowed((prev) => ({ ...prev, [p.id]: [] }))
  }

  const providerChangeCount = (p: Provider): number => {
    let n = 0
    if (p.id in pendingEnabled && pendingEnabled[p.id] !== p.enabled) n += 1
    if (p.id in pendingAllowed && hasRealChanges(p)) n += 1
    return n
  }

  const applyProviderChanges = async (p: Provider) => {
    setApplyingId(p.id)
    setFormError('')
    try {
      if (p.id in pendingAllowed && hasRealChanges(p)) {
        await apiPatch<Provider>(`/providers/${p.id}`, {
          allowed_models: pendingAllowed[p.id],
        })
      }
      if (p.id in pendingEnabled && pendingEnabled[p.id] !== p.enabled) {
        await apiPatch<Provider>(`/providers/${p.id}`, {
          enabled: pendingEnabled[p.id],
        })
      }
      await queryClient.invalidateQueries({ queryKey: ['providers'] })
      await queryClient.invalidateQueries({ queryKey: ['models'] })
      await queryClient.invalidateQueries({ queryKey: ['defaults'] })
      setPendingAllowed((prev) => {
        const next = { ...prev }
        delete next[p.id]
        return next
      })
      setPendingEnabled((prev) => {
        const next = { ...prev }
        delete next[p.id]
        return next
      })
    } catch (e) {
      setFormError((e as Error).message)
    } finally {
      setApplyingId(null)
    }
  }

  const discardProvider = (p: Provider) => {
    setPendingAllowed((prev) => {
      const next = { ...prev }
      delete next[p.id]
      return next
    })
    setPendingEnabled((prev) => {
      const next = { ...prev }
      delete next[p.id]
      return next
    })
  }

  const saveDefaultModel = async () => {
    setSavingDefaultModel(true)
    setDefaultModelError('')
    try {
      await apiPatch<DefaultsConfig>('/defaults', { default_model: defaultModel })
      await queryClient.invalidateQueries({ queryKey: ['defaults'] })
      setDefaultModelSaved(true)
      setTimeout(() => setDefaultModelSaved(false), 2000)
    } catch (e) {
      setDefaultModelError((e as Error).message)
    } finally {
      setSavingDefaultModel(false)
    }
  }

  const saveUtilityModel = async () => {
    setSavingUtilityModel(true)
    setUtilityModelError('')
    try {
      await apiPatch<DefaultsConfig>('/defaults', { utility_model: utilityModel })
      await queryClient.invalidateQueries({ queryKey: ['defaults'] })
      setUtilityModelSaved(true)
      setTimeout(() => setUtilityModelSaved(false), 2000)
    } catch (e) {
      setUtilityModelError((e as Error).message)
    } finally {
      setSavingUtilityModel(false)
    }
  }

  return (
    <Layout>
      <div className="mx-auto w-full max-w-3xl flex-1 overflow-y-auto px-4 py-8">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-indigo-700/20">
            <Settings className="size-5 text-indigo-300" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-zinc-100">Settings</h1>
            <p className="mt-0.5 text-sm text-zinc-500">
              Manage models. Open a provider to pick which of its models are allowed in chat.
            </p>
          </div>
        </div>

        <div className="mt-6">
          <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-400">Defaults</h2>
          <div className="mt-3">
            <DefaultsSettings />
          </div>
        </div>

        <div className="mt-6">
          <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-400">Models</h2>

          <div className="mt-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
            <h3 className="text-sm font-medium text-zinc-100">Chat model</h3>
            <p className="mt-1 text-xs text-zinc-500">
              The model new conversations start with. You can still change it per conversation
              in the composer.
            </p>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <select
                value={defaultModel}
                onChange={(e) => setDefaultModel(e.target.value)}
                className="min-w-64 flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-indigo-600"
              >
                <option value="">No default (use last used)</option>
                {(allModels ?? []).map((m) => (
                  <option key={`${m.provider_id}::${m.id}`} value={`${m.provider_id}::${m.id}`}>
                    {m.provider_name} — {m.id}
                  </option>
                ))}
              </select>
              <Button
                onClick={() => void saveDefaultModel()}
                loading={savingDefaultModel}
                disabled={!defaultModelDirty}
              >
                {defaultModelSaved ? <Check className="size-4" /> : <Save className="size-4" />}
                {defaultModelSaved ? 'Saved' : 'Save'}
              </Button>
            </div>

            {defaultModelError && <p className="mt-3 text-sm text-red-400">{defaultModelError}</p>}
          </div>

          <div className="mt-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
            <h3 className="text-sm font-medium text-zinc-100">Utility model</h3>
            <p className="mt-1 text-xs text-zinc-500">
              A smaller or cheaper model for background work — conversation titles and memory
              extraction. Leave it on “Same as chat model” to use the chat model.
            </p>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <select
                value={utilityModel}
                onChange={(e) => setUtilityModel(e.target.value)}
                className="min-w-64 flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-indigo-600"
              >
                <option value="">Same as chat model</option>
                {(allModels ?? []).map((m) => (
                  <option key={`${m.provider_id}::${m.id}`} value={`${m.provider_id}::${m.id}`}>
                    {m.provider_name} — {m.id}
                  </option>
                ))}
              </select>
              <Button
                onClick={() => void saveUtilityModel()}
                loading={savingUtilityModel}
                disabled={!utilityModelDirty}
              >
                {utilityModelSaved ? <Check className="size-4" /> : <Save className="size-4" />}
                {utilityModelSaved ? 'Saved' : 'Save'}
              </Button>
            </div>

            {utilityModelError && <p className="mt-3 text-sm text-red-400">{utilityModelError}</p>}
          </div>

          {providers?.length === 0 && (
            <p className="mt-3 rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-3 text-sm text-zinc-400">
              No providers added yet. Add your first provider below.
            </p>
          )}

          <div className="mt-3 space-y-3">
            {(providers ?? []).map((p) => {
              const isExpanded = expandedId === p.id
              const models = modelsByProvider[p.id] ?? []
              const loading = loadingModels[p.id]
              const allowed = allowedIds(p, models)
              const enabled = effectiveEnabled(p)
              const effAllowed = effectiveAllowed(p)
              const query = modelSearch.trim().toLowerCase()
              const visible = (query ? models.filter((m) => m.id.toLowerCase().includes(query)) : models)
                .slice()
                .sort((a, b) => Number(allowed.has(b.id)) - Number(allowed.has(a.id)))
              const whitelistText =
                effAllowed === null
                  ? 'all models allowed'
                  : `${effAllowed.length} model${effAllowed.length === 1 ? '' : 's'} allowed`
              const isPending = hasRealChanges(p)

              return (
                <div
                  key={p.id}
                  className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/60"
                >
                  <button
                    onClick={() => void toggleExpand(p)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-zinc-900"
                  >
                    <ChevronDown
                      className={`size-4 shrink-0 text-zinc-500 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-medium text-zinc-100">{p.name}</span>
                        <span className="shrink-0 rounded-full bg-zinc-800 px-2 py-0.5 text-[11px] text-zinc-400">
                            {providerTypes?.find((t) => t.id === p.type)?.name ?? p.type}
                        </span>
                        <span
                          className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${
                            enabled ? 'bg-indigo-600/15 text-indigo-400' : 'bg-zinc-800 text-zinc-500'
                          }`}
                        >
                          {enabled ? 'enabled' : 'disabled'}
                        </span>
                        {isPending && (
                          <span className="shrink-0 rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] text-amber-400">
                            pending
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500">
                        {p.base_url && (
                          <span className="flex items-center gap-1">
                            <Server className="size-3" /> <code>{p.base_url}</code>
                          </span>
                        )}
                        <span className="flex items-center gap-1">
                          <KeyRound className="size-3" />{' '}
                          {p.api_key_masked
                            ? p.api_key_masked
                              : providerTypes?.find((t) => t.id === p.type)?.requires_api_key
                              ? 'no key'
                              : 'no key needed'}
                        </span>
                        <span>{whitelistText}</span>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => startEdit(p)}
                        className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
                        title="Edit"
                      >
                        <Pencil className="size-4" />
                      </button>
                      <button
                        onClick={() => toggleEnabled(p)}
                        className={`rounded-lg p-2 ${enabled ? 'text-indigo-400 hover:bg-indigo-600/10' : 'text-zinc-500 hover:bg-zinc-800'}`}
                        title={enabled ? 'Disable' : 'Enable'}
                      >
                        {enabled ? <Check className="size-4" /> : <X className="size-4" />}
                      </button>
                      <button
                        onClick={() => void remove(p.id)}
                        className="rounded-lg p-2 text-zinc-400 hover:bg-red-500/10 hover:text-red-400"
                        title="Delete"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                  </button>

                  {isExpanded && (
                    <div className="border-t border-zinc-800 px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="relative flex-1">
                          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-zinc-500" />
                          <input
                            value={modelSearch}
                            onChange={(e) => setModelSearch(e.target.value)}
                            placeholder="Search models…"
                            className="w-full rounded-lg border border-zinc-700 bg-zinc-900 py-1.5 pl-8 pr-3 text-xs text-zinc-200 outline-none focus:border-indigo-600"
                          />
                        </div>
                        <button
                          onClick={() => selectAll(p, models)}
                          className="flex shrink-0 items-center gap-1 rounded-lg border border-zinc-700 px-2.5 py-1.5 text-xs text-indigo-400 hover:bg-zinc-800"
                          title="Allow all models"
                        >
                          <CheckSquare className="size-3.5" /> All
                        </button>
                        <button
                          onClick={() => selectNone(p)}
                          className="flex shrink-0 items-center gap-1 rounded-lg border border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-400 hover:bg-zinc-800"
                          title="Allow no models"
                        >
                          <Square className="size-3.5" /> None
                        </button>
                        <button
                          onClick={() => void fetchModels(p)}
                          className="flex shrink-0 items-center gap-1 rounded-lg border border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-400 hover:bg-zinc-800"
                          title="Refresh models"
                        >
                          <RefreshCw className={`size-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
                        </button>
                      </div>

                      {unreachable[p.id] && (
                        <div className="mt-3 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                          <AlertTriangle className="size-3.5 shrink-0" />
                          Some saved models are unavailable — the provider may be unreachable, or a
                          model may have been removed.
                        </div>
                      )}

                      {loading ? (
                        <div className="mt-3 flex items-center gap-2 text-xs text-zinc-500">
                          <Loader2 className="size-3.5 animate-spin" /> Fetching models…
                        </div>
                      ) : models.length === 0 ? (
                        <p className="mt-3 text-xs text-zinc-500">
                          No models returned (check key/base URL) or provider disabled.
                        </p>
                      ) : visible.length === 0 ? (
                        <p className="mt-3 text-xs text-zinc-500">
                          No models match “{modelSearch}”.
                        </p>
                      ) : (
                        <>
                          <p className="mt-3 text-xs text-zinc-400">
                            {visible.length} of {models.length} models — checked models appear in chat:
                          </p>
                          <div className="mt-1.5 max-h-64 space-y-0.5 overflow-y-auto pr-1">
                            {visible.map((m) => (
                              <label
                                key={m.id}
                                className={`flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1 text-xs ${
                                  m.available === false
                                    ? 'text-red-400 hover:bg-red-500/10'
                                    : 'text-zinc-200 hover:bg-zinc-800/70'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={allowed.has(m.id)}
                                  onChange={() => toggleModel(p, models, m.id)}
                                  className="size-3.5 accent-indigo-600"
                                />
                                <span className="min-w-0 flex-1 truncate">{m.id}</span>
                                {m.available === false && (
                                  <span className="shrink-0 text-[10px] text-red-400">
                                    {m.reason === 'removed' ? 'removed' : 'unreachable'}
                                  </span>
                                )}
                                {m.context_window && (
                                  <span className="shrink-0 text-[10px] text-zinc-500">
                                    {Math.round(m.context_window / 1000)}k ctx
                                  </span>
                                )}
                              </label>
                            ))}
                          </div>
                          <p className="mt-2 text-[11px] text-zinc-500">
                            Changes apply when you press Apply. “All” is the default when no selection was made.
                          </p>
                        </>
                      )}

                      {hasRealChanges(p) && (
                        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-zinc-800 pt-3">
                          <Button
                            size="sm"
                            onClick={() => void applyProviderChanges(p)}
                            loading={applyingId === p.id}
                          >
                            <Check className="size-4" />
                            Apply {providerChangeCount(p)} change{providerChangeCount(p) === 1 ? '' : 's'}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => discardProvider(p)}>
                            Discard
                          </Button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        <div className="mt-8 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
          <h2 className="text-sm font-medium text-zinc-100">
            {editingId ? 'Edit provider' : 'Add provider'}
          </h2>
          <p className="mt-1 text-xs text-zinc-500">
            Connect an API or local endpoint to make its models available in chat.
          </p>

          <div className="mt-4 space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-xs text-zinc-400">Provider type</span>
                <select
                  value={type}
                  onChange={(e) => onTypeChange(e.target.value)}
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-indigo-600"
                >
                  {(providerTypes ?? []).map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-xs text-zinc-400">Display name</span>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="My provider" />
              </label>
            </div>

            {typeMeta?.requires_api_key && (
              <label className="block">
                <span className="mb-1.5 block text-xs text-zinc-400">API key</span>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={editingId ? 'Leave blank to keep existing key' : 'sk-…'}
                />
              </label>
            )}

            <label className="block">
              <span className="mb-1.5 block text-xs text-zinc-400">Base URL</span>
              <Input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={typeMeta?.requires_base_url ? 'https://your-endpoint/v1' : 'https://…'}
              />
            </label>

            {formError && <p className="text-sm text-red-400">{formError}</p>}

            {testResult && (
              <div
                className={`rounded-lg border px-3 py-2 text-sm ${
                  testResult.ok
                    ? 'border-indigo-600/30 bg-indigo-600/10 text-indigo-300'
                    : 'border-red-500/30 bg-red-500/10 text-red-300'
                }`}
              >
                {testResult.message}
                {testResult.ok && testResult.models.length > 0 && (
                  <div className="mt-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-zinc-400">
                        Select the models allowed in chat ({selectedModels.size} of{' '}
                        {testResult.models.length}):
                      </span>
                      <div className="flex items-center gap-3">
                        <button
                          type="button"
                          onClick={() => setSelectedModels(new Set(testResult.models.map((m) => m.id)))}
                          className="flex items-center gap-1 text-xs text-indigo-400 hover:underline"
                        >
                          <CheckSquare className="size-3.5" /> All
                        </button>
                        <button
                          type="button"
                          onClick={() => setSelectedModels(new Set())}
                          className="flex items-center gap-1 text-xs text-zinc-400 hover:underline"
                        >
                          <Square className="size-3.5" /> None
                        </button>
                      </div>
                    </div>
                    <div className="relative mt-2">
                      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-zinc-500" />
                      <input
                        value={formModelSearch}
                        onChange={(e) => setFormModelSearch(e.target.value)}
                        placeholder="Search models…"
                        className="w-full rounded-lg border border-zinc-700 bg-zinc-900 py-1.5 pl-8 pr-3 text-xs text-zinc-200 outline-none focus:border-indigo-600"
                      />
                    </div>
                    <div className="mt-2 max-h-48 space-y-1 overflow-y-auto pr-1">
                      {testResult.models
                        .filter((m) =>
                          formModelSearch.trim()
                            ? m.id.toLowerCase().includes(formModelSearch.trim().toLowerCase())
                            : true,
                        )
                        .map((m) => (
                        <label
                          key={m.id}
                          className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-800/70"
                        >
                          <input
                            type="checkbox"
                            checked={selectedModels.has(m.id)}
                            onChange={() => toggleFormModel(m.id)}
                            className="size-3.5 accent-indigo-600"
                          />
                          <span className="min-w-0 flex-1 truncate">{m.id}</span>
                          {m.context_window && (
                            <span className="shrink-0 text-[10px] text-zinc-500">
                              {Math.round(m.context_window / 1000)}k
                            </span>
                          )}
                        </label>
                      ))}
                    </div>
                    <p className="mt-2 text-[11px] text-zinc-500">
                      Only checked models will appear in the chat model list. If you save without testing,
                      all models are allowed.
                    </p>
                  </div>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" onClick={() => void testConnection()} loading={testing}>
                <Plug className="size-4" /> Test &amp; fetch models
              </Button>
              <Button onClick={() => void save()} loading={saving}>
                {editingId ? <Check className="size-4" /> : <Plus className="size-4" />}
                {editingId ? 'Save changes' : 'Add provider'}
              </Button>
              {editingId && (
                <Button variant="ghost" onClick={resetForm}>
                  Cancel
                </Button>
              )}
            </div>
          </div>
        </div>

        <OcrSettings />

        <div className="mt-6">
          <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-400">Web</h2>
          <div className="mt-3">
            <SearchSettings />
          </div>
        </div>
      </div>
    </Layout>
  )
}
