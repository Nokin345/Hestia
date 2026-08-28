import { QueryClient } from '@tanstack/react-query'
import { experimental_createQueryPersister } from '@tanstack/query-persist-client-core'

const PERSIST_PREFIX = 'hestia:query'
const PERSIST_BUSTER = 'hestia-v1'
const MODELS_SNAPSHOT_KEY = 'hestia:lastModels'

// Persist only cheap GET queries that are safe to hydrate from cache: model
// lists, providers, conversations, memory stats and search/embedding config.
// Streaming chat and per-conversation messages are intentionally excluded.
function shouldPersist(key: unknown): boolean {
  if (!Array.isArray(key) || typeof key[0] !== 'string') return false
  const first = key[0]
  return (
    first === 'models' ||
    first === 'providers' ||
    first === 'conversations' ||
    first === 'memories' ||
    first === 'memory-stats' ||
    first === 'search-config' ||
    first === 'embedding-config' ||
    first === 'embedding-stats'
  )
}

const persister = experimental_createQueryPersister({
  storage: {
    getItem(key: string) {
      try {
        return window.localStorage.getItem(key)
      } catch {
        return null
      }
    },
    setItem(key: string, value: string) {
      try {
        window.localStorage.setItem(key, value)
      } catch {
        // Quota exceeded or private mode - ignore.
      }
    },
    removeItem(key: string) {
      try {
        window.localStorage.removeItem(key)
      } catch {
        // ignore
      }
    },
  },
  prefix: PERSIST_PREFIX,
  buster: PERSIST_BUSTER,
  filters: { predicate: (query) => shouldPersist(query.queryKey) },
})

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        refetchOnWindowFocus: false,
        // How long restored cache stays "fresh" before background revalidation.
        staleTime: 60_000,
        persister: persister.persisterFn,
      },
    },
  })
}

// Synchronous last-known models snapshot for instant dropdown population on
// load, independent of React Query's async cache restore/refetch. The exact
// signatures are deliberately loose to avoid a hard import edge on ModelEntry.
export function readLastModels<T = Record<string, unknown>>(): T[] {
  try {
    const raw = window.localStorage.getItem(MODELS_SNAPSHOT_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function writeLastModels(models: unknown): void {
  if (!Array.isArray(models) || models.length === 0) return
  try {
    window.localStorage.setItem(MODELS_SNAPSHOT_KEY, JSON.stringify(models))
  } catch {
    // ignore storage failures
  }
}