import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, Database, Hammer, Plus, Paperclip, PlugZap, RotateCcw, SlidersHorizontal } from 'lucide-react'
import { clsx } from 'clsx'
import type { McpToolDef, SystemPromptPreset } from '../../api/types'

type SubmenuKey = 'prompt' | 'integrations' | null

interface ComposerMenuProps {
  systemPrompt: string
  temperature: number
  kbEnabled: boolean
  memoryEnabled: boolean
  mcpTools: string[]
  mcpAllTools: McpToolDef[]
  presets: SystemPromptPreset[]
  onKbToggle: () => void
  onMemoryToggle: () => void
  onMcpToolToggle: (toolName: string) => void
  onSystemPromptChange: (v: string) => void
  onTemperatureChange: (v: number) => void
  onApplyPreset: (content: string) => void
  onAttachFiles: () => void
  onResetPrompt: () => void
}

export function ComposerMenu({
  systemPrompt,
  temperature,
  kbEnabled,
  memoryEnabled,
  mcpTools,
  mcpAllTools,
  presets,
  onKbToggle,
  onMemoryToggle,
  onMcpToolToggle,
  onSystemPromptChange,
  onTemperatureChange,
  onApplyPreset,
  onAttachFiles,
  onResetPrompt,
}: ComposerMenuProps) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState<SubmenuKey>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const promptTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const integrationsTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        close()
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const close = () => {
    setOpen(false)
    setActive(null)
  }

  const scheduleClose = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closeTimer.current = setTimeout(() => setActive(null), 200)
  }
  const cancelClose = () => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }

  const enterPrompt = () => {
    if (integrationsTimer.current) clearTimeout(integrationsTimer.current)
    promptTimer.current = setTimeout(() => setActive('prompt'), 80)
  }
  const leavePrompt = () => {
    if (promptTimer.current) clearTimeout(promptTimer.current)
  }

  const enterIntegrations = () => {
    if (promptTimer.current) clearTimeout(promptTimer.current)
    integrationsTimer.current = setTimeout(() => setActive('integrations'), 80)
  }
  const leaveIntegrations = () => {
    if (integrationsTimer.current) clearTimeout(integrationsTimer.current)
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        title="Composer options"
        onClick={() => (open ? close() : setOpen(true))}
        className={clsx(
          'flex size-8 shrink-0 items-center justify-center rounded-lg border transition-colors',
          open
            ? 'border-indigo-700/50 bg-indigo-600/10 text-indigo-300'
            : 'border-zinc-700 bg-zinc-900 text-zinc-500',
        )}
      >
        <Plus className="size-4" />
      </button>

      {open && (
        <>
          <div className="absolute bottom-full left-0 z-50 mb-2 origin-bottom-left">
            {/* main column */}
            <div
              className="relative flex w-56 flex-col rounded-lg border border-zinc-700 bg-zinc-900/95 p-1.5 shadow-2xl shadow-black/50 backdrop-blur"
              onMouseLeave={scheduleClose}
              onMouseEnter={cancelClose}
            >
              <button
                type="button"
                onClick={onAttachFiles}
                className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm text-zinc-200 transition-colors hover:bg-zinc-800"
              >
                <Paperclip className="size-4 text-zinc-400" />
                Attach files
              </button>

              <button
                type="button"
                onMouseEnter={enterPrompt}
                onMouseLeave={leavePrompt}
                onClick={() => setActive(active === 'prompt' ? null : 'prompt')}
                className={clsx(
                  'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors',
                  active === 'prompt' ? 'bg-indigo-600/15 text-indigo-300' : 'text-zinc-200 hover:bg-zinc-800',
                )}
              >
                <SlidersHorizontal className="size-4 text-zinc-400" />
                System prompt
                <span className="ml-auto text-zinc-500">›</span>
              </button>

              <button
                type="button"
                onMouseEnter={enterIntegrations}
                onMouseLeave={leaveIntegrations}
                onClick={() => setActive(active === 'integrations' ? null : 'integrations')}
                className={clsx(
                  'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors',
                  active === 'integrations' ? 'bg-indigo-600/15 text-indigo-300' : 'text-zinc-200 hover:bg-zinc-800',
                )}
              >
                <Hammer className="size-4 text-zinc-400" />
                Integrations
                <span className="ml-auto text-zinc-500">›</span>
              </button>

              {/* integrations flyout */}
              {active === 'integrations' && (
                <div
                  onMouseEnter={cancelClose}
                  onMouseLeave={scheduleClose}
                  className="absolute bottom-0 left-full ml-1 flex w-72 flex-col gap-1 rounded-lg border border-zinc-700 bg-zinc-900/95 p-1.5 shadow-2xl shadow-black/50 backdrop-blur"
                >
                  <div className="flex items-center justify-between rounded-md px-2.5 py-2">
                    <span className="flex items-center gap-2.5 text-sm text-zinc-200">
                      <BookOpen className="size-4 text-emerald-400" />
                      Knowledge base
                    </span>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={kbEnabled}
                      onClick={onKbToggle}
                      className={clsx(
                        'flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors',
                        kbEnabled ? 'bg-indigo-600 justify-end' : 'bg-zinc-700 justify-start',
                      )}
                    >
                      <span className="size-4 rounded-full bg-white shadow" />
                    </button>
                  </div>
                  <div className="flex items-center justify-between rounded-md px-2.5 py-2">
                    <span className="flex items-center gap-2.5 text-sm text-zinc-200">
                      <Database className="size-4 text-indigo-400" />
                      Memory
                    </span>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={memoryEnabled}
                      onClick={onMemoryToggle}
                      className={clsx(
                        'flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors',
                        memoryEnabled ? 'bg-indigo-600 justify-end' : 'bg-zinc-700 justify-start',
                      )}
                    >
                      <span className="size-4 rounded-full bg-white shadow" />
                    </button>
                  </div>
                  <div className="mt-0.5 border-t border-zinc-800 pt-1.5">
                    <div className="flex items-center justify-between px-2.5 pb-1">
                      <span className="flex items-center gap-2.5 text-sm text-zinc-200">
                        <PlugZap className="size-4 text-emerald-400" />
                        MCP tools
                      </span>
                      <Link
                        to="/mcp"
                        onClick={close}
                        className="rounded-md px-1.5 py-0.5 text-[11px] font-medium text-indigo-400 transition-colors hover:bg-indigo-600/10"
                      >
                        Manage
                      </Link>
                    </div>
                    <div className="px-1.5 pb-1 text-[11px] text-zinc-600">
                      Pick which MCP tools this conversation may use.
                    </div>
                    {mcpAllTools.length === 0 ? (
                      <div className="rounded-md border border-dashed border-zinc-700 px-2.5 py-2 text-center text-[11px] text-zinc-600">
                        No servers configured — add them in MCP settings.
                      </div>
                    ) : (
                      <div className="flex max-h-56 flex-col gap-0.5 overflow-y-auto pb-1">
                        {mcpAllTools.map((t) => {
                          const on = mcpTools.includes(t.name)
                          return (
                            <div
                              key={t.name}
                              className="flex items-center justify-between gap-2 rounded-md px-2 py-1"
                            >
                              <span
                                className="flex min-w-0 items-center gap-1.5"
                                title={t.description}
                              >
                                <span className="truncate text-sm text-zinc-200">
                                  {t.raw_name}
                                </span>
                                <span className="shrink-0 rounded bg-emerald-950/60 px-1 text-[10px] text-emerald-400/80">
                                  {t.server}
                                </span>
                              </span>
                              <button
                                type="button"
                                role="switch"
                                aria-checked={on}
                                onClick={() => onMcpToolToggle(t.name)}
                                className={clsx(
                                  'flex h-4 w-7 shrink-0 items-center rounded-full px-0.5 transition-colors',
                                  on
                                    ? 'bg-emerald-600 justify-end'
                                    : 'bg-zinc-700 justify-start',
                                )}
                              >
                                <span className="size-3 rounded-full bg-white shadow" />
                              </button>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* prompt flyout */}
              {active === 'prompt' && (
                <div
                  onMouseEnter={cancelClose}
                  onMouseLeave={scheduleClose}
                  className="absolute bottom-0 left-full ml-1 flex w-80 flex-col gap-3 rounded-lg border border-zinc-700 bg-zinc-900/95 p-3 shadow-2xl shadow-black/50 backdrop-blur"
                >
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-zinc-400">System prompt</label>
                    <button
                      type="button"
                      onClick={onResetPrompt}
                      className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-indigo-400"
                    >
                      <RotateCcw className="size-3" />
                      Reset
                    </button>
                  </div>
                  <textarea
                    value={systemPrompt}
                    onChange={(e) => onSystemPromptChange(e.target.value)}
                    rows={6}
                    placeholder="e.g. You are a concise, witty assistant."
                    className="w-full resize-none rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 outline-none transition-colors focus:border-indigo-600 focus:ring-2 focus:ring-indigo-600/30"
                  />
                  {presets.length > 0 && (
                    <div>
                      <label className="text-xs font-medium text-zinc-400">Presets</label>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {presets.map((p) => (
                          <button
                            key={p.id}
                            type="button"
                            onClick={() => onApplyPreset(p.content)}
                            title={`Apply "${p.name}"`}
                            className="rounded-full border border-zinc-700 bg-zinc-800/60 px-2.5 py-1 text-xs text-zinc-300 transition-colors hover:border-indigo-600 hover:text-indigo-300"
                          >
                            {p.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-zinc-400">Temperature</label>
                    <span
                      className={clsx(
                        'rounded-md border px-1.5 py-0.5 text-xs',
                        temperature > 1.5
                          ? 'border-red-500/50 bg-red-500/10 text-red-400'
                          : 'border-zinc-700 bg-zinc-950 text-indigo-300',
                      )}
                    >
                      {temperature.toFixed(2)}
                    </span>
                  </div>
                  <div className="relative h-12">
                    <input
                      type="range"
                      min={0}
                      max={2}
                      step={0.05}
                      value={temperature}
                      onChange={(e) => onTemperatureChange(parseFloat(e.target.value))}
                      className={clsx(
                        'w-full',
                        temperature > 1.5 ? 'accent-red-600' : 'accent-indigo-600',
                      )}
                    />
                    <span
                      title="Default (0.7)"
                      className="pointer-events-none absolute left-[35%] top-[10px] h-3 w-px -translate-x-1/2 -translate-y-1/2 rounded bg-zinc-500/70"
                    />
                    <span className="pointer-events-none absolute left-0 top-8 text-[10px] leading-none text-zinc-600">
                      Precise
                    </span>
                    <span className="pointer-events-none absolute left-[35%] top-8 -translate-x-1/2 text-[10px] leading-none text-zinc-600">
                      default
                    </span>
                    <span className="pointer-events-none absolute right-0 top-8 text-[10px] leading-none text-zinc-600">
                      Creative
                    </span>
                    {temperature > 1.5 && (
                      <span className="pointer-events-none absolute inset-x-0 -bottom-0.5 text-center text-[10px] leading-none text-red-400">
                        High temperature warning — outputs become unpredictable
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
