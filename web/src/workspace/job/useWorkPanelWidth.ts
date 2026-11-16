import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "aos.workPanelWidth";
const DEFAULT_WIDTH = 480;
const MIN_WIDTH = 300;
const MAX_WIDTH = 920;

function readStoredWidth(): number {
  if (typeof window === "undefined") return DEFAULT_WIDTH;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const n = raw ? Number.parseInt(raw, 10) : NaN;
    if (Number.isFinite(n) && n >= MIN_WIDTH && n <= MAX_WIDTH) return n;
  } catch {
    /* ignore */
  }
  return DEFAULT_WIDTH;
}

function clampWidth(px: number, viewportWidth: number): number {
  const max = Math.min(MAX_WIDTH, Math.round(viewportWidth * 0.78));
  return Math.min(max, Math.max(MIN_WIDTH, Math.round(px)));
}

export function useWorkPanelWidth() {
  const [width, setWidth] = useState(readStoredWidth);

  useEffect(() => {
    setWidth(readStoredWidth());
  }, []);

  const persist = useCallback((next: number) => {
    const clamped = clampWidth(next, window.innerWidth);
    setWidth(clamped);
    try {
      localStorage.setItem(STORAGE_KEY, String(clamped));
    } catch {
      /* ignore */
    }
  }, []);

  const resetWidth = useCallback(() => {
    persist(DEFAULT_WIDTH);
  }, [persist]);

  const startResize = useCallback(
    (clientX: number) => {
      const startX = clientX;
      const startWidth = width;

      const onMove = (e: PointerEvent) => {
        const delta = startX - e.clientX;
        persist(startWidth + delta);
      };

      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
        document.body.style.removeProperty("cursor");
        document.body.style.removeProperty("user-select");
      };

      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    },
    [persist, width],
  );

  return { width, startResize, resetWidth, minWidth: MIN_WIDTH, maxWidth: MAX_WIDTH };
}
