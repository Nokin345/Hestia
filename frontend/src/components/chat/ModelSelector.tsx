import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Server } from 'lucide-react'
import type { ModelEntry } from '../../api/types'

export interface ModelGroup {
  providerId: string
  providerName: string
  models: ModelEntry[]
}

export default function ModelSelector({
  groups,
  value,
  onChange,
  disabled,
}: {
  groups: ModelGroup[]
  value: string
  onChange: (v: string) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
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

  const flat = groups.flatMap((g) => g.models)
  const selected = flat.find((m) => `${m.provider_id}::${m.id}` === value)
  const label = selected ? selected.id : (value.split('::').pop() ?? 'No models available')
  const noModels = groups.length === 0

  return (
    <div ref={rootRef} className="relative ml-auto min-w-0 max-w-[45%] shrink">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        title={label}
        className={`flex w-full min-w-0 items-center gap-1.5 rounded-lg border bg-zinc-900 px-2.5 py-1.5 text-xs outline-none transition-colors disabled:opacity-50 ${
          open
            ? 'border-indigo-600 text-zinc-100'
            : 'border-zinc-700 text-zinc-300 hover:bg-zinc-800 focus:border-indigo-600'
        }`}
      >
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <ChevronDown
          className={`size-3.5 shrink-0 text-zinc-500 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 bottom-full z-50 mb-1 max-h-72 w-64 overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900/95 py-1 shadow-2xl shadow-black/50 backdrop-blur">
          {noModels ? (
            <div className="px-3 py-2 text-xs text-zinc-500">No models available</div>
          ) : (
            groups.map((g) => (
              <div key={g.providerId}>
                <div className="flex items-center gap-1.5 px-3 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                  <Server className="size-3 shrink-0" />
                  {g.providerName}
                </div>
                {g.models.map((m) => {
                  const key = `${g.providerId}::${m.id}`
                  const active = key === value
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => {
                        onChange(key)
                        setOpen(false)
                      }}
                      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs ${
                        active
                          ? 'bg-indigo-600/15 text-indigo-300'
                          : 'text-zinc-200 hover:bg-zinc-800'
                      }`}
                    >
                      <span className="min-w-0 flex-1 truncate">{m.id}</span>
                      {active && <Check className="size-3.5 shrink-0 text-indigo-400" />}
                    </button>
                  )
                })}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
