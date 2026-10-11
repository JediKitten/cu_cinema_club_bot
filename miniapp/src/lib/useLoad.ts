import { useCallback, useEffect, useRef, useState } from 'react'

export interface LoadState<T> {
  data: T | undefined
  error: string | undefined
  loading: boolean
  reload: () => void
  /** Локально подменить данные (оптимистичное обновление) */
  setData: (updater: (prev: T | undefined) => T | undefined) => void
}

/**
 * Загрузка данных экрана. При перезагрузке прежние данные остаются
 * на экране (как в текущем проде), ошибка показывается плашкой.
 * Если в проекте уже есть свой useLoad с таким же контрактом — используйте его.
 */
export function useLoad<T>(fn: () => Promise<T>, deps: readonly unknown[]): LoadState<T> {
  const [data, setDataState] = useState<T>()
  const [error, setError] = useState<string>()
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const fnRef = useRef(fn)
  useEffect(() => {
    fnRef.current = fn
  })

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(undefined)
    fnRef.current()
      .then((d) => alive && setDataState(d))
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps задаёт вызывающий
  }, [...deps, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  const setData = useCallback((updater: (prev: T | undefined) => T | undefined) => setDataState(updater), [])

  return { data, error, loading, reload, setData }
}
