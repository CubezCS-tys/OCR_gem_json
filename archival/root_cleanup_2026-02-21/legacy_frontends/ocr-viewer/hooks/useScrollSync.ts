"use client";

import { useCallback, useRef } from "react";

const DEBOUNCE_MS = 80;

export function useScrollSync(enabled: boolean) {
  const lockSource = useRef<"left" | "right" | null>(null);
  const lockTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rafId = useRef<number | null>(null);

  const leftRef = useRef<HTMLDivElement>(null);
  // Right panel can be an iframe (HTML mode) or a div (searchable PDF mode)
  const rightRef = useRef<HTMLIFrameElement | HTMLDivElement>(null);

  const getScrollPercent = (el: HTMLElement): number => {
    const maxScroll = el.scrollHeight - el.clientHeight;
    if (maxScroll <= 0) return 0;
    return el.scrollTop / maxScroll;
  };

  const setScrollPercent = (el: HTMLElement, percent: number) => {
    const maxScroll = el.scrollHeight - el.clientHeight;
    el.scrollTop = percent * maxScroll;
  };

  const getRightScrollElement = (): HTMLElement | null => {
    const el = rightRef.current;
    if (!el) return null;
    // If it's an iframe, get the documentElement inside
    if (el instanceof HTMLIFrameElement) {
      return el.contentDocument?.documentElement ?? null;
    }
    // Otherwise it's a div, use it directly
    return el;
  };

  const clearLock = useCallback(() => {
    if (lockTimer.current) clearTimeout(lockTimer.current);
    lockTimer.current = setTimeout(() => {
      lockSource.current = null;
    }, DEBOUNCE_MS);
  }, []);

  const handleLeftScroll = useCallback(() => {
    if (!enabled) return;
    if (lockSource.current === "right") return;

    lockSource.current = "left";
    clearLock();

    if (rafId.current) cancelAnimationFrame(rafId.current);
    rafId.current = requestAnimationFrame(() => {
      const left = leftRef.current;
      const right = getRightScrollElement();
      if (!left || !right) return;

      const percent = getScrollPercent(left);
      setScrollPercent(right, percent);
    });
  }, [enabled, clearLock]);

  const handleRightScroll = useCallback(() => {
    if (!enabled) return;
    if (lockSource.current === "left") return;

    lockSource.current = "right";
    clearLock();

    if (rafId.current) cancelAnimationFrame(rafId.current);
    rafId.current = requestAnimationFrame(() => {
      const left = leftRef.current;
      const right = getRightScrollElement();
      if (!left || !right) return;

      const percent = getScrollPercent(right);
      setScrollPercent(left, percent);
    });
  }, [enabled, clearLock]);

  return {
    leftRef,
    rightRef,
    handleLeftScroll,
    handleRightScroll,
  };
}
