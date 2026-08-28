import { Layout } from '../components/layout/Layout'

export function PlaceholderPage({
  title,
  description,
  phase,
}: {
  title: string
  description: string
  phase: string
}) {
  return (
    <Layout>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
        <h1 className="text-lg font-semibold text-zinc-100">{title}</h1>
        <p className="max-w-md text-sm text-zinc-500">{description}</p>
        <span className="mt-2 rounded-full border border-indigo-600/30 bg-indigo-600/10 px-3 py-1 text-xs text-indigo-400">
          {phase}
        </span>
      </div>
    </Layout>
  )
}
