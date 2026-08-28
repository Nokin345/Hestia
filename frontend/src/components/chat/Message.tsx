import { memo, useLayoutEffect, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import { Check, ChevronRight, Copy, Pencil, Send, Trash2, Wrench, X, FileText, ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import type { ChatUsage, Message, MessagePart } from '../../api/types'
import type { RetrievedMemory, KbSource } from '../../api/stream'
import { Button } from '../ui'

function prettyJson(input: string): string {
  const trimmed = input?.trim?.() ?? ''
  if (!trimmed) return input ?? ''
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2)
  } catch {
    return input
  }
}

interface ParsedToolBlock {
  name: string
  status: string
  args: string
  content: string
}

// MCP tools are namespaced as "<server>.<tool>". Built-in tools have no dot.
function splitMcpName(name: string): { server: string | null; tool: string } {
  const i = name.indexOf('.')
  if (i <= 0 || i === name.length - 1) return { server: null, tool: name }
  return { server: name.slice(0, i), tool: name.slice(i + 1) }
}

export interface ThinkingBubble {
  kind: 'thinking'
  text: string
}

export interface ToolGroupBubble {
  kind: 'toolGroup'
  blocks: ParsedToolBlock[]
}

export interface AnswerBubble {
  kind: 'answer'
  text: string
}

export type AssistantBubble = ThinkingBubble | ToolGroupBubble | AnswerBubble

function parseText(s: string): string {
  try {
    const v = JSON.parse(s)
    return typeof v === 'string' ? v : JSON.stringify(v, null, 2)
  } catch {
    return s
  }
}

function parseArgsObject(raw: string): Record<string, unknown> | null {
  try {
    const v = JSON.parse(raw)
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null
  } catch {
    return null
  }
}

// run_code's args are {"code": "..."} — show the raw code snippet rather than
// the JSON envelope. Everything else falls back to pretty-printed JSON.
function formatToolInput(name: string, args: string): string {
  if (name === 'run_code') {
    const obj = parseArgsObject(args)
    const code = obj?.code
    if (typeof code === 'string') return code
  }
  return prettyJson(args)
}

// run_code may pass a language arg (defaults to python) — surface it as a
// small note on the tool chip.
function runCodeLanguage(name: string, args: string): string | null {
  if (name !== 'run_code') return null
  const obj = parseArgsObject(args)
  const lang = obj?.language
  return typeof lang === 'string' && lang ? lang : null
}

// New format: "<name> | ok|failed\nA<len>\n<args_json>\nC<len>\n<body_json>"
// Old format: "<name> | ok | <args...>\n---\n<content>"
//
// Arguments and result bodies are always JSON-encoded, so they never contain
// raw newlines (JSON.stringify escapes them as "\n"). We therefore locate block
// boundaries structurally instead of trusting the A/C length prefix — which was
// computed with Python len() (code points) while JS .length counts UTF-16 code
// units, breaking multi-block payloads that include astral-plane characters.
function parseToolBlocks(text: string): ParsedToolBlock[] {
  const blocks: ParsedToolBlock[] = []
  let i = 0
  while (i < text.length) {
    while (text[i] === '\n') i += 1
    const nl = text.indexOf('\n', i)
    if (nl === -1) break
    const header = text.slice(i, nl)
    const hMatch = header.match(/^(.+?) \| (ok|failed)$/)
    if (!hMatch) break
    const name = hMatch[1]
    const status = hMatch[2]

    let j = nl + 1
    if (text[j] !== 'A') break
    const aNl = text.indexOf('\n', j)
    if (aNl === -1) break
    const aEnd = text.indexOf('\n', aNl + 1)
    if (aEnd === -1) break
    const args = parseText(text.slice(aNl + 1, aEnd))

    if (text[aEnd + 1] !== 'C') break
    const cNl = text.indexOf('\n', aEnd + 2)
    if (cNl === -1) break
    const cEnd = text.indexOf('\n', cNl + 1)
    const content = parseText(text.slice(cNl + 1, cEnd === -1 ? text.length : cEnd))
    blocks.push({ name, status, args, content })
    i = cEnd
  }
  if (blocks.length === 0) {
    for (const block of text.split('\n\n')) {
      const idx = block.indexOf('\n---\n')
      const meta = idx === -1 ? block : block.slice(0, idx)
      const content = idx === -1 ? '' : block.slice(idx + 5)
      if (!meta.trim()) continue
      const parts = meta.split(' | ')
      blocks.push({
        name: parts[0] || '',
        status: parts[1] || '',
        args: parts.slice(2).join(' | '),
        content,
      })
    }
  }
  return blocks
}

/**
 * Derive an assistant "turn" bubble list from the raw message rows of one
 * turn. One turn (everything emitted by the assistant after a user message) is
 * displayed as a single unit:
 *   - a "thinking" bubble per reasoning part (pre-tool and final reasoning)
 *   - one "tool" bubble per tool-call block (parsed from tool row text)
 *   - an "answer" bubble (inference) containing the assistant's text
 */
export function buildTurnBubbles(rows: Array<{ role: string; parts: MessagePart[]; tool_results?: unknown }>): AssistantBubble[] {
  const bubbles: AssistantBubble[] = []
  for (const row of rows) {
    const text = row.parts
      .filter((p) => p.type === 'text')
      .map((p) => p.text ?? '')
      .join('')
    const reasoning = row.parts
      .filter((p) => p.type === 'reasoning')
      .map((p) => p.text ?? '')
      .join('')
    if (row.role === 'tool') {
      for (const block of parseToolBlocks(text)) {
        // Every tool call renders as the chip-style group bubble — a single
        // tool is just a group of one. Models often loop calls back-to-back, so
        // consecutive blocks merge into one compact "chain" card.
        const prev = bubbles[bubbles.length - 1]
        if (prev && prev.kind === 'toolGroup') {
          prev.blocks.push(block)
        } else {
          bubbles.push({ kind: 'toolGroup', blocks: [block] })
        }
      }
      continue
    }
    if (reasoning) bubbles.push({ kind: 'thinking', text: reasoning })
    if (text.trim()) bubbles.push({ kind: 'answer', text })
  }
  return bubbles
}

// During streaming the assistant's parts only carry reasoning + text so far,
// while tool results arrive as separate rows the same way they persist. This
// helper is what the live view uses to render the in-flight turn unit.
export function bubbleStatus(b: AssistantBubble): string | null {
  if (b.kind === 'toolGroup') return b.blocks[b.blocks.length - 1]?.status ?? null
  return null
}

// If a tool-call bubble acts as a placeholder while the result streams in
// (no content yet), it renders with an animated "calling" indicator.
export function isPendingToolBubble(b: AssistantBubble): boolean {
  if (b.kind === 'toolGroup') return b.blocks.some((blk) => !blk.content)
  return false
}

// remark-math allows spaces inside `$...$` spans, so currency amounts like
// "$5 and $10" would otherwise be swallowed as math. Before the markdown
// parser sees the text, first mask all paired `$...$` spans that contain
// math-like content (LaTeX commands, operators, or multiple word chars).
// Then escape every remaining `$` — these are guaranteed to be currency.
// Genuine formulas such as `$C_5–C_{12}$`, `$0^3$`, `$5.50$`, `$2025 =$`,
// or `$\frac{1}{2}$` are left untouched.
function protectCurrency(raw: string): string {
  const protectedBlocks: string[] = []
  const mask = (m: string) => {
    protectedBlocks.push(m)
    return `\u0000${protectedBlocks.length - 1}\u0000`
  }
  let out = raw.replace(/```[\s\S]*?```/g, mask)
  out = out.replace(/`[^`]*`/g, mask)
  out = out.replace(/\$\$[\s\S]*?\$\$/g, mask)
  // Mask paired $...$ spans whose content looks like math
  out = out.replace(/\$[^$]*?\$/g, (m) => {
    const inner = m.slice(1, -1)
    // LaTeX commands, operators, or grouping → math
    if (/[\\^_{}=+*\/()\[\]]/.test(inner)) return mask(m)
    // Single letter variable (e.g. $E$, $x$) → math
    if (/^[A-Za-z]+$/.test(inner)) return mask(m)
    // Long content → likely math
    if (inner.length > 20) return mask(m)
    return m
  })
  // Every remaining $ is now currency — escape it
  out = out.replace(/\$/g, '\\$')
  return out.replace(/\u0000(\d+)\u0000/g, (_, i) => protectedBlocks[Number(i)])
}

// remark-math parses single-line `$$...$$` as inline math, so it never gets
// the `katex-display` wrapper (and no display styling applies). This promotes
// a paragraph that is entirely math to the exact `math` (display) node shape
// remark-math produces for `\n$$\n...\n$$\n` blocks.
function remarkPromoteDisplayMath() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (tree: any) => {
    const visit = (node: any, cb: (n: any) => void) => {
      cb(node)
      for (const c of node.children ?? []) visit(c, cb)
    }
    visit(tree, (node) => {
      if (node.type !== 'paragraph') return
      const [only] = node.children
      if (node.children.length !== 1 || only.type !== 'inlineMath') return
      only.type = 'math'
      only.data = {
        hName: 'pre',
        hChildren: [
          {
            type: 'element',
            tagName: 'code',
            properties: { className: ['language-math', 'math-display'] },
            children: [{ type: 'text', value: only.value }],
          },
        ],
      }
    })
  }
}

function UsageFooter({ usage }: { usage: ChatUsage }) {
  const parts: string[] = []
  if (usage.input_tokens != null) parts.push(`↑ ${usage.input_tokens}`)
  if (usage.output_tokens != null) parts.push(`↓ ${usage.output_tokens}`)
  if (usage.tokens_per_second != null) parts.push(`${usage.tokens_per_second} tok/s`)
  if (parts.length === 0) return null
  const details = [
    usage.input_tokens != null ? `Input tokens: ${usage.input_tokens}` : null,
    usage.output_tokens != null ? `Output tokens: ${usage.output_tokens}` : null,
    usage.tokens_per_second != null ? `Tokens per second: ${usage.tokens_per_second}` : null,
  ]
    .filter(Boolean)
    .join('\n')
  return (
    <div
      className="flex w-fit items-center gap-1 text-[11px] text-zinc-500"
      title={details}
    >
      {parts.join(' · ')}
    </div>
  )
}

function nodeText(node: React.ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(nodeText).join('')
  if (node && typeof node === 'object' && 'props' in node) {
    return nodeText((node as { props: { children?: React.ReactNode } }).props.children)
  }
  return ''
}

function CodeBlock({ children }: { children: React.ReactNode }) {
  const text = nodeText(children)
  const lang = codeLanguage(children)
  const [copied, setCopied] = useState(false)
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className="group/code my-3 overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-800/80 px-3 py-1.5">
        <span className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
          {lang || 'text'}
        </span>
        <button
          onClick={onCopy}
          title="Copy code"
          className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-white"
        >
          {copied ? <Check className="size-3 text-indigo-400" /> : <Copy className="size-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="my-0! overflow-x-auto p-3 text-sm">{children}</pre>
    </div>
  )
}

// rehype-highlight stamps the fence's language onto the <code> element as a
// `language-<lang>` class — surface it as a small label above the code.
function codeLanguage(children: React.ReactNode): string | null {
  if (!children || typeof children !== 'object' || !('props' in children)) return null
  const props = (children as { props?: { className?: unknown } }).props
  const cls = props?.className
  if (typeof cls !== 'string') return null
  const m = cls.match(/language-([\w-]+)/)
  return m ? m[1] : null
}

export const Markdown = memo(function Markdown({
  content,
  className = 'prose-chat',
}: {
  content: string
  className?: string
}) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath, remarkPromoteDisplayMath]}
        rehypePlugins={[[rehypeHighlight, { detect: false }], rehypeKatex]}
        components={{ pre: ({ children }) => <CodeBlock>{children}</CodeBlock> }}
      >
        {protectCurrency(content)}
      </ReactMarkdown>
    </div>
  )
})

function ThinkingBubbleView({ text, isStreaming }: { text: string; isStreaming?: boolean }) {
  const contentRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = contentRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [text])
  return (
    <div data-bubble className="w-fit min-w-0 max-w-full">
      <details className="group rounded-lg border border-zinc-800 bg-zinc-900/60" open={isStreaming}>
        <summary className="flex cursor-pointer select-none items-center gap-2 px-3 py-2 text-xs font-medium text-zinc-400 hover:text-zinc-200">
          <span className="transition-transform group-open:rotate-90">
            <ChevronRight className="size-3.5" />
          </span>
          {isStreaming ? (
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-flex gap-1">
                <span className="size-1.5 animate-pulse rounded-full bg-zinc-500" />
                <span className="size-1.5 animate-pulse rounded-full bg-zinc-500 [animation-delay:-0.3s]" />
                <span className="size-1.5 animate-pulse rounded-full bg-zinc-500 [animation-delay:-0.15s]" />
              </span>
              Thinking…
            </span>
          ) : (
            <span className="text-zinc-500">View thinking process</span>
          )}
        </summary>
        <div
          ref={contentRef}
          className="max-h-64 overflow-auto whitespace-pre-wrap border-t border-zinc-800 px-3 py-2 text-xs leading-relaxed text-zinc-500"
        >
          {text}
        </div>
      </details>
    </div>
  )
}

function ToolResultBody({ block }: { block: ParsedToolBlock }) {
  return (
    <div className="flex flex-col gap-1">
      {block.args && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-1.5">
          <div className="text-[10px] uppercase tracking-wide text-zinc-600">Input</div>
          <pre className="mt-0.5 max-h-64 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-zinc-300">
            {formatToolInput(block.name, block.args)}
          </pre>
        </div>
      )}
      <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-1.5">
        <div className="text-[10px] uppercase tracking-wide text-zinc-600">Output</div>
        <pre className="mt-0.5 max-h-64 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-zinc-300">
          {prettyJson(block.content)}
        </pre>
      </div>
    </div>
  )
}

// One clickable chip per step in a tool chain. Toggling a chip selects it;
// its result is rendered in the shared panel below the row of cards.
function ToolChip({
  block,
  active,
  pending,
  onToggle,
}: {
  block: ParsedToolBlock
  active?: boolean
  pending?: boolean
  onToggle: () => void
}) {
  const passed = block.status === 'ok'
  const { server, tool } = splitMcpName(block.name)
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`flex min-w-0 items-center gap-1.5 rounded-lg border px-1.5 py-1 text-[11px] transition-colors ${
        active
          ? 'border-indigo-500/60 bg-indigo-600/15 text-indigo-200'
          : 'border-zinc-800 bg-zinc-950/50 text-zinc-300 hover:border-zinc-700'
      }`}
    >
      {server && (
        <span
          className="shrink-0 rounded bg-emerald-500/15 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-emerald-400"
          title={`MCP server: ${server}`}
        >
          {server}
        </span>
      )}
      <span className={`truncate font-medium ${active ? '' : 'text-indigo-400/80'}`}>
        {tool}
      </span>
      {runCodeLanguage(block.name, block.args) && (
        <span className="shrink-0 rounded bg-amber-500/15 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-amber-400">
          {runCodeLanguage(block.name, block.args)}
        </span>
      )}
      {pending ? (
        <span className="inline-flex shrink-0 gap-0.5">
          <span className="size-1 animate-pulse rounded-full bg-indigo-400" />
          <span className="size-1 animate-pulse rounded-full bg-indigo-400 [animation-delay:-0.3s]" />
          <span className="size-1 animate-pulse rounded-full bg-indigo-400 [animation-delay:-0.15s]" />
        </span>
      ) : (
        <span
          className={`shrink-0 text-[10px] font-medium ${passed ? 'text-emerald-400' : 'text-red-400'}`}
        >
          {block.status}
        </span>
      )}
    </button>
  )
}

// One compact group bubble for a chain of back-to-back tool calls: a header
// with the count, a row of step chips, and a SINGLE shared result panel below.
// Only one step is expanded at a time; selecting another swaps the panel.
function ToolChainBubble({
  blocks,
  pending,
}: {
  blocks: ParsedToolBlock[]
  pending?: boolean
}) {
  const [open, setOpen] = useState<number | null>(null)
  const active = open !== null ? blocks[open] : undefined
  return (
    <div
      data-bubble
      className="flex w-fit min-w-0 max-w-full flex-col gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900/60 px-2 py-1.5 text-[11px] text-zinc-400"
    >
      <span className="flex min-w-0 items-center gap-1.5">
        <Wrench className="size-3 shrink-0 text-indigo-400" />
        <span className="shrink-0 font-medium text-zinc-300">Tools</span>
        <span className="shrink-0 rounded bg-zinc-800 px-1 text-[10px] text-zinc-400">
          {blocks.length}
        </span>
      </span>
      <div className="flex flex-wrap items-start gap-1">
        {blocks.map((block, i) => (
          <ToolChip
            key={i}
            block={block}
            active={open === i}
            pending={pending && !block.content}
            onToggle={() => setOpen((cur) => (cur === i ? null : i))}
          />
        ))}
      </div>
      {active && active.content && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-1.5">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wide text-zinc-600">
              Result · step #{open! + 1}
            </span>
            <button
              type="button"
              onClick={() => setOpen(null)}
              className="text-[10px] text-zinc-500 hover:text-zinc-300"
            >
              close
            </button>
          </div>
          <div className="mt-1">
            <ToolResultBody block={active} />
          </div>
        </div>
      )}
    </div>
  )
}

function ToolCallStatus({ name }: { name: string }) {
  return (
    <div className="mt-1.5 inline-flex items-center gap-1.5 rounded-lg border border-indigo-600/30 bg-indigo-600/10 px-2 py-1 text-[11px] text-indigo-300">
      <Wrench className="size-3 animate-pulse" />
      Calling {name}
      <span className="inline-flex gap-0.5">
        <span className="size-1 animate-pulse rounded-full bg-indigo-400" />
        <span className="size-1 animate-pulse rounded-full bg-indigo-400 [animation-delay:-0.3s]" />
        <span className="size-1 animate-pulse rounded-full bg-indigo-400 [animation-delay:-0.15s]" />
      </span>
    </div>
  )
}

function TypingIndicator({ label = 'Thinking…' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-zinc-400">
      <span className="inline-flex gap-1">
        <span className="size-1.5 animate-pulse rounded-full bg-zinc-400" />
        <span className="size-1.5 animate-pulse rounded-full bg-zinc-400 [animation-delay:-0.3s]" />
        <span className="size-1.5 animate-pulse rounded-full bg-zinc-400 [animation-delay:-0.15s]" />
      </span>
      <span className="text-[11px]">{label}</span>
    </span>
  )
}

function MemoryPill({
  memories,
  isStreaming,
}: {
  memories: RetrievedMemory[]
  isStreaming?: boolean
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const pinned = memories.filter((m) => m.type === 'pinned').length
  const recalled = memories.filter((m) => m.type === 'recalled').length
  const label = [
    pinned ? `${pinned} pinned` : '',
    recalled ? `${recalled} recalled` : '',
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-full border border-zinc-700/50 bg-zinc-800/40 px-2.5 py-1 text-[11px] text-zinc-400 transition-colors hover:bg-zinc-800/70 hover:text-zinc-300"
        title={memories.map((m) => `[${m.type}] ${m.text}`).join('\n')}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 2a7 7 0 0 1 7 7c0 2.5-1.3 4.8-3.5 6-.3.2-.5.5-.5.9V18h-6v-2.1c0-.4-.2-.7-.5-.9C6.3 13.8 5 11.5 5 9a7 7 0 0 1 7-7z" />
          <path d="M9 18h6v1a3 3 0 0 1-6 0v-1z" />
          <path d="M12 2v7" />
          <path d="M8.5 6.5L12 9l3.5-2.5" />
        </svg>
        <span>{isStreaming ? `${memories.length} retrieved…` : label}</span>
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-72 rounded-lg border border-zinc-700 bg-zinc-900/95 p-1.5 shadow-2xl shadow-black/50 backdrop-blur">
          {memories.map((m, i) => (
            <div key={i} className="flex items-start gap-2 rounded-md px-2 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800">
              <span
                className={`mt-0.5 shrink-0 rounded px-1 text-[10px] ${
                  m.type === 'pinned'
                    ? 'bg-zinc-700/60 text-zinc-300'
                    : 'bg-zinc-700/60 text-zinc-400'
                }`}
              >
                {m.type}
              </span>
              <span className="min-w-0 flex-1 leading-snug">{m.text}</span>
              <span className="shrink-0 text-[10px] text-zinc-500">{m.category}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function KbPill({ sources, lineRanges }: { sources: KbSource[]; lineRanges?: Record<string, [number, number][]> }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const cachedRanges = useRef<Record<string, [number, number][]>>({})

  if (lineRanges && Object.keys(lineRanges).length > 0) {
    cachedRanges.current = lineRanges
  }
  const activeRanges = lineRanges && Object.keys(lineRanges).length > 0 ? lineRanges : cachedRanges.current

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const names = [...new Set(sources.map((s) => s.filename))]

  const fmtLines = (ranges: [number, number][]): string =>
    ranges.map(([s, e]) => (s === e ? `line ${s}` : `line ${s}-${e}`)).join(', ')

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-full border border-zinc-700/50 bg-zinc-800/40 px-2.5 py-1 text-[11px] text-zinc-400 transition-colors hover:bg-zinc-800/70 hover:text-zinc-300"
        title={names.join(', ')}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M16 13H8" />
          <path d="M16 17H8" />
          <path d="M10 9H8" />
        </svg>
        <span>
          {names.length === 1 ? names[0] : `${names.length} files`}
        </span>
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-max rounded-lg border border-zinc-700 bg-zinc-900/95 p-1.5 shadow-2xl shadow-black/50 backdrop-blur">
          {names.map((name) => {
            const ranges = activeRanges?.[name]
            return (
              <div key={name} className="flex items-start gap-2 rounded-md px-2 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0 text-zinc-500" aria-hidden="true">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <path d="M14 2v6h6" />
                </svg>
                <span className="whitespace-nowrap text-zinc-300">
                  {ranges && ranges.length > 0 ? fmtLines(ranges) : ''}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function EditBox({
  value,
  onChange,
  onConfirm,
  onCancel,
  confirmLabel = 'Send',
  align = 'right',
}: {
  value: string
  onChange: (v: string) => void
  onConfirm: () => void
  onCancel: () => void
  confirmLabel?: string
  align?: 'right' | 'left'
}) {
  const rounded = align === 'right' ? 'rounded-br-md' : 'rounded-bl-md'
  return (
    <div className={`flex ${align === 'right' ? 'justify-end' : 'justify-start'}`}>
      <div className={`w-full ${align === 'right' ? 'max-w-[85%]' : 'max-w-[90%]'}`}>
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              onConfirm()
            }
          }}
          autoFocus
          rows={Math.min(8, Math.max(1, value.split('\n').length))}
          className={`max-h-60 w-full resize-none rounded-2xl ${rounded} border border-indigo-700/50 bg-zinc-900 px-4 py-2.5 text-sm text-white outline-none focus:border-indigo-600`}
        />
        <div className={`mt-1.5 flex gap-2 ${align === 'right' ? 'justify-end' : 'justify-start'}`}>
          <Button variant="ghost" size="sm" onClick={onCancel}>
            <X className="size-4" /> Cancel
          </Button>
          <Button size="sm" onClick={onConfirm} disabled={!value.trim()}>
            <Send className="size-4" /> {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}

function ActionButtons({ onEdit, onDelete }: { onEdit?: () => void; onDelete?: () => void }) {
  return (
    <div className="mt-1 flex items-center gap-1 opacity-0 transition-opacity pointer-coarse:opacity-100 group-hover:opacity-100">
      {onEdit && (
        <button
          onClick={onEdit}
          title="Edit message"
          className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
        >
          <Pencil className="size-3" /> Edit
        </button>
      )}
      {onDelete && (
        <button
          onClick={onDelete}
          title="Delete message"
          className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-zinc-500 hover:bg-red-500/10 hover:text-red-400"
        >
          <Trash2 className="size-3" /> Delete
        </button>
      )}
    </div>
  )
}

function SenderLabel({ name, align }: { name: string; align: 'left' | 'right' }) {
  return (
    <div
      className={`mb-1 flex ${align === 'right' ? 'justify-end' : 'justify-start'} px-0.5 text-[11px] font-medium ${
        align === 'right' ? 'text-indigo-300/80' : 'text-zinc-500'
      }`}
    >
      {name}
    </div>
  )
}

function DocumentChip({
  name,
  url,
  text,
}: {
  name: string
  url?: string | null
  text?: string | null
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title={text ? 'Click to expand document text' : name}
        className="flex h-20 max-w-48 items-center gap-2 rounded-lg border border-zinc-700/60 bg-zinc-800/80 px-3 text-left transition-colors hover:border-indigo-600/50"
      >
        <FileText className="size-5 shrink-0 text-indigo-400" />
        <span className="truncate text-xs text-zinc-200">{name}</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 max-h-64 w-80 overflow-auto rounded-lg border border-zinc-700 bg-zinc-900/95 p-3 text-xs leading-relaxed text-zinc-300 shadow-2xl shadow-black/50 backdrop-blur">
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="mb-1.5 flex items-center gap-1.5 break-all font-medium text-indigo-300 hover:underline"
            >
              <ExternalLink className="size-3 shrink-0" />
              {name}
            </a>
          )}
          {text && <div className="whitespace-pre-wrap">{text}</div>}
        </div>
      )}
    </div>
  )
}

export function MessageBubble({
  message,
  username,
  onEdit,
  onDelete,
}: {
  message: Message
  username?: string
  onEdit?: () => void
  onDelete?: () => void
}) {
  const text = message.parts.filter((p) => p.type === 'text').map((p) => p.text ?? '').join('')
  const images = message.parts.filter((p) => p.type === 'image_url' && p.image_url)
  const docs = message.parts.filter((p) => p.type === 'document' && (p.url || p.text))

  if (message.role === 'user') {
    return (
      <div className="group flex justify-end">
        <div className="flex max-w-[85%] flex-col items-end">
          <SenderLabel name={username || 'You'} align="right" />
          {(images.length > 0 || docs.length > 0) && (
            <div className="mb-1.5 flex max-w-full flex-wrap justify-end gap-1.5">
              {images.map((img, i) => (
                <a
                  key={`img-${i}`}
                  href={img.image_url!}
                  target="_blank"
                  rel="noreferrer"
                  className="shrink-0"
                >
                  <img
                    src={img.image_url!}
                    alt="attachment"
                    className="size-20 rounded-lg border border-zinc-700/60 object-cover transition-colors hover:border-indigo-600/50"
                  />
                </a>
              ))}
              {docs.map((d, i) => (
                <DocumentChip key={`doc-${i}`} name={d.name || 'document'} url={d.url} text={d.text} />
              ))}
            </div>
          )}
          {text && (
            <div className="w-fit rounded-2xl rounded-br-md bg-indigo-900/70 px-4 py-2.5 text-sm text-white">
              <div className="whitespace-pre-wrap">{text}</div>
            </div>
          )}
          <ActionButtons onEdit={onEdit} onDelete={onDelete} />
        </div>
      </div>
    )
  }

  return null
}

function ErrorBubble({ message }: { message: string }) {
  return (
    <div
      data-bubble
      className="w-fit rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300"
    >
      {message}
    </div>
  )
}

function AnswerBubbleView({
  text,
  isStreaming,
  streamingLabel = 'Generating…',
}: {
  text: string
  isStreaming?: boolean
  streamingLabel?: string
}) {
  return (
    <div
      data-bubble
      className="w-fit min-w-8 max-w-full rounded-2xl rounded-bl-md bg-slate-900 px-4 py-2.5 text-sm text-white"
    >
      {text ? (
        <Markdown content={text} className="prose-chat prose-chat-on-bubble" />
      ) : isStreaming ? (
        <TypingIndicator label={streamingLabel} />
      ) : (
        <TypingIndicator label="…" />
      )}
    </div>
  )
}

// Timeline connector: each bubble keeps its position. A dot hangs off its left
// edge at its vertical center (CSS-only via top:50%, so no re-measurement
// during streaming), a short line links the dot to the bubble, and the unit
// draws one continuous vertical rail behind them.
function TimelineRow({ children, connectDown }: { children: ReactNode; connectDown?: boolean }) {
  return (
    <div className={`relative ${connectDown ? 'mb-1.5' : ''}`}>
      <span
        data-timeline-dot
        className="absolute left-[-12px] top-1/2 size-2 -translate-y-1/2 rounded-full bg-zinc-600/60"
      />
      <span className="absolute left-[-4px] top-1/2 h-px w-1 -translate-y-1/2 bg-zinc-700/50" />
      <div className="min-w-0">{children}</div>
    </div>
  )
}

export function AssistantTurn({
  rows,
  senderName,
  isStreaming,
  expectsReasoning,
  activeTool,
  showSender = true,
  onEdit,
  onDelete,
}: {
  rows: Array<{ role: string; parts: MessagePart[]; error?: string | null; usage?: ChatUsage | null; memories_used?: Message['memories_used'] | null; retrieved_memories?: RetrievedMemory[]; retrieved_kb?: KbSource[]; retrievedMemories?: RetrievedMemory[]; retrievedKb?: KbSource[]; kbLineRanges?: Record<string, [number, number][]> }>
  senderName?: string
  isStreaming?: boolean
  expectsReasoning?: boolean
  activeTool?: string | null
  showSender?: boolean
  onEdit?: () => void
  onDelete?: () => void
}) {
  const bubbles = buildTurnBubbles(rows)
  const lastAssistant = [...rows].reverse().find((r) => r.role === 'assistant')
  if (bubbles.length === 0 && !lastAssistant?.error && !isStreaming) return null

  const reasoningPending =
    isStreaming &&
    expectsReasoning !== false &&
    !rows.some(
      (r) => r.role === 'assistant' && r.parts.some((p) => p.type === 'text' && (p.text ?? '').length > 0),
    )
  const thinkingOpenIndex = bubbles.reduce(
    (last, b, i) => (b.kind === 'thinking' ? i : last),
    -1,
  )
  const streamingLabel = activeTool ? `Calling ${activeTool}…` : reasoningPending ? 'Thinking…' : 'Generating…'
  const retrievedMemories = lastAssistant?.retrievedMemories || lastAssistant?.retrieved_memories || []
  const retrievedKb = lastAssistant?.retrievedKb || lastAssistant?.retrieved_kb || []
  const kbLineRanges = (lastAssistant as { kbLineRanges?: Record<string, [number, number][]> } | undefined)?.kbLineRanges

  const bubbleEls: ReactNode[] = []
  if (bubbles.length === 0 && isStreaming) {
    bubbleEls.push(
      <AnswerBubbleView key="placeholder" text="" isStreaming streamingLabel={streamingLabel} />,
    )
  } else {
    bubbles.forEach((b, i) => {
      const el =
        b.kind === 'thinking' ? (
          <ThinkingBubbleView
            key={i}
            text={b.text}
            isStreaming={isStreaming && reasoningPending && thinkingOpenIndex === i}
          />
        ) : b.kind === 'toolGroup' ? (
          <ToolChainBubble
            key={i}
            blocks={b.blocks}
            pending={isStreaming && b.blocks.some((x) => !x.content)}
          />
        ) : (
          <AnswerBubbleView key={i} text={b.text} isStreaming={isStreaming} streamingLabel={streamingLabel} />
        )
      bubbleEls.push(el)
    })
  }
  if (lastAssistant?.error) {
    bubbleEls.push(<ErrorBubble key="error" message={lastAssistant.error} />)
  }

  const railRef = useRef<HTMLDivElement>(null)
  const [railRange, setRailRange] = useState<[number, number] | null>(null)

  useLayoutEffect(() => {
    const el = railRef.current
    if (!el || bubbleEls.length === 0) {
      setRailRange(null)
      return
    }
    const measure = () => {
      const dots = el.querySelectorAll<HTMLElement>('[data-timeline-dot]')
      if (dots.length === 0) {
        setRailRange(null)
        return
      }
      const elRect = el.getBoundingClientRect()
      const first = dots[0].getBoundingClientRect()
      const last = dots[dots.length - 1].getBoundingClientRect()
      setRailRange([
        first.top + first.height / 2 - elRect.top,
        last.top + last.height / 2 - elRect.top,
      ])
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [bubbleEls.length])

  return (
    <div className="group flex justify-start">
      <div className="min-w-0 max-w-[90%] flex-1">
        {showSender && <SenderLabel name={senderName || 'Assistant'} align="left" />}
        <div ref={railRef} className="relative flex flex-col">
          {bubbleEls.length > 1 ? (
            <>
              {railRange && (
                <span
                  className="absolute w-px bg-zinc-700/50"
                  style={{ left: -8, top: railRange[0], height: Math.max(0, railRange[1] - railRange[0]) }}
                />
              )}
              {bubbleEls.map((el, i) => (
                <TimelineRow key={i} connectDown={i < bubbleEls.length - 1}>
                  {el}
                </TimelineRow>
              ))}
            </>
          ) : (
            bubbleEls
          )}
          {isStreaming && activeTool && <ToolCallStatus name={activeTool} />}
        </div>
        {(lastAssistant?.usage || lastAssistant?.error) && (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
            {retrievedMemories.length > 0 && <MemoryPill memories={retrievedMemories} isStreaming={isStreaming} />}
            {retrievedKb.length > 0 && <KbPill sources={retrievedKb} lineRanges={kbLineRanges} />}
            {lastAssistant.usage && <UsageFooter usage={lastAssistant.usage} />}
          </div>
        )}
        <ActionButtons onEdit={onEdit} onDelete={onDelete} />
      </div>
    </div>
  )
}
