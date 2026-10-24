import { ref, onUnmounted } from 'vue'

export type Participant = {
  id: number; name: string; status: string; persona: string; intent?: string;
  steps: number; max_steps: number; message?: string; url?: string; action?: string; error?: string;
}
export type Snapshot = {
  status: string; message: string; run_id?: string; phase?: string; label?: string;
  current?: number; total?: number; participants: Participant[]; error?: string;
  started_at?: string; finished_at?: string; start_url?: string;
}

export function useProgress(pollMs = 1000, runId?: string) {
  const data = ref<Snapshot>({ status: 'idle', message: 'No run started yet.', participants: [] })
  const error = ref<string | null>(null)
  const lastUpdated = ref<Date | null>(null)
  let timer: number | null = null
  let active = false
  let controller: AbortController | null = null

  const fetchOnce = async () => {
    if (controller) return
    controller = new AbortController()
    const timeout = window.setTimeout(() => controller?.abort(), 10000)
    try {
      const query = runId ? `?run_id=${encodeURIComponent(runId)}` : ''
      const res = await fetch(`/progress${query}`, { cache: 'no-store', signal: controller.signal })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error || `HTTP ${res.status}`)
      }
      data.value = await res.json()
      error.value = null
      lastUpdated.value = new Date()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch progress'
    } finally {
      clearTimeout(timeout)
      controller = null
    }
  }
  const poll = async () => {
    await fetchOnce()
    if (active) timer = window.setTimeout(poll, pollMs)
  }
  const start = () => {
    if (active) return
    active = true
    void poll()
  }
  const stop = () => {
    active = false
    if (timer !== null) clearTimeout(timer)
    timer = null
    controller?.abort()
  }
  onUnmounted(stop)
  return { data, error, lastUpdated, start, stop, fetchOnce }
}
