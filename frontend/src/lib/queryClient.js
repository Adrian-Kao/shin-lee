import { QueryClient } from '@tanstack/react-query';

/**
 * Single shared QueryClient (P1③).
 *
 * Server state moves here from hand-written useState+useEffect+fetch. Benefits:
 *   - de-dupe: two components asking for the same queryKey share ONE request
 *     (e.g. the audit-verify chip in AppShell + the AuditView page).
 *   - caching + staleness: re-entering a route doesn't blindly refetch.
 *   - retry/backoff is centralised (client.js already retries 429/5xx; React
 *     Query adds query-level retry on top, kept conservative here).
 *
 * Defaults are intentionally modest for a POC: short stale window, one retry.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
});
