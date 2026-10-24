import { useCallback, useEffect, useState } from "react";
import { errorText } from "./api";

export function useLoad<T>(
  loader: () => Promise<T>,
  dependencies: unknown[] = [],
) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((key) => key + 1), []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    loader()
      .then((value) => {
        if (active) setData(value);
      })
      .catch((reason) => {
        if (active) setError(errorText(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // Loader identity intentionally excluded: callers list primitive query dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, reloadKey]);
  return { data, error, loading, reload, setData };
}
export function useDraft<T>(key: string, initial: T) {
  const [value, updateValue] = useState<T>(() => {
    try {
      const saved = localStorage.getItem(key);
      return saved ? (JSON.parse(saved) as T) : initial;
    } catch {
      return initial;
    }
  });
  const setValue = (next: T) => {
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      /* beforeunload still protects in-memory edits. */
    }
    updateValue(next);
  };
  return { value, setValue, clear: () => localStorage.removeItem(key) };
}
export function useBeforeUnload(dirty: boolean) {
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
}
