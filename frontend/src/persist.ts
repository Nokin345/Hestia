import { QueryClient } from '@tanstack/react-query'
import { persistQueryClient } from '@tanstack/react-query-persist-client'
import type { Persister, PersistedClient } from '@tanstack/query-persist-client-core'

const PERSIST_PREFIX = 'hestia:query'
const PERSIST_BUSTER = 'hestia-v1'
const MODELS_SNAPSHOT_KEY = 'hestia:lastModels'

function shouldPersist(key: unknown): boolean {
  if (!Array.isArray(key) || typeof key[0] !== 'string') return false
  const first = key[0]
  return (
    first === 'providers' ||
    first === 'conversations' ||
    first === 'memories' ||
    first === 'memory-stats' ||
    first === 'search-config' ||
    first === 'embedding-stats'
  )
}

const persister: Persister = {
  persistClient: async (client: PersistedClient) => {
    try {
      window.localStorage.setItem(
        PERSIST_PREFIX,
        JSON.stringify({
          timestamp: client.timestamp,
          buster: client.buster,
          clientState: client.clientState,
        }),
      )
    } catch {
      // ignore storage failures
    }
  },
  restoreClient: async () => {
    try {
      const raw = window.localStorage.getItem(PERSIST_PREFIX)
      if (!raw) return undefined
      const data = JSON.parse(raw)
      return {
        timestamp: data.timestamp,
        buster: data.buster,
        clientState: data.clientState,
      }
    } catch {
      return undefined
    }
  },
  removeClient: async () => {
    try {
      window.localStorage.removeItem(PERSIST_PREFIX)
    } catch {
      // ignore
    }
  },
}

export function createAppQueryClient(): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        refetchOnWindowFocus: false,
        staleTime: 60_000,
      },
    },
  })

  persistQueryClient({
    queryClient: client,
    persister,
    buster: PERSIST_BUSTER,
    dehydrateOptions: {
      shouldDehydrateQuery: (query) => shouldPersist(query.queryKey),
    },
  })

  return client
}

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
