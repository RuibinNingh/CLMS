import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";

export function HelpTip({
  label,
  children,
}: {
  label: string;
  children: string;
}) {
  const id = useId(),
    trigger = useRef<HTMLButtonElement>(null),
    bubble = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [open, setOpen] = useState(false),
    [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  function cancelTimer() {
    clearTimeout(timer.current);
  }
  function close() {
    cancelTimer();
    setOpen(false);
    setPinned(false);
  }
  function leave() {
    cancelTimer();
    if (!pinned) timer.current = setTimeout(() => setOpen(false), 150);
  }
  useEffect(() => () => clearTimeout(timer.current), []);
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const anchor = trigger.current?.getBoundingClientRect(),
        box = bubble.current?.getBoundingClientRect();
      if (!anchor || !box) return;
      setPosition({
        left: Math.max(
          12,
          Math.min(
            innerWidth - box.width - 12,
            anchor.left + anchor.width / 2 - box.width / 2,
          ),
        ),
        top:
          anchor.bottom + box.height + 12 > innerHeight
            ? Math.max(12, anchor.top - box.height - 8)
            : anchor.bottom + 8,
      });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    const outside = (event: PointerEvent) => {
      if (
        !trigger.current?.contains(event.target as Node) &&
        !bubble.current?.contains(event.target as Node)
      )
        close();
    };
    document.addEventListener("keydown", key);
    document.addEventListener("pointerdown", outside);
    return () => {
      document.removeEventListener("keydown", key);
      document.removeEventListener("pointerdown", outside);
    };
  }, [open]);
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="help-trigger"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onFocus={() => {
          cancelTimer();
          setOpen(true);
        }}
        onBlur={() => {
          if (!pinned) close();
        }}
        onPointerEnter={(event) => {
          if (
            event.pointerType === "mouse" &&
            matchMedia("(hover: hover) and (pointer: fine)").matches
          ) {
            cancelTimer();
            timer.current = setTimeout(() => setOpen(true), 300);
          }
        }}
        onPointerLeave={leave}
        onClick={() => {
          cancelTimer();
          if (pinned) close();
          else {
            setPinned(true);
            setOpen(true);
          }
        }}
      >
        <Icon name="info" />
      </button>
      {open &&
        createPortal(
          <div
            ref={bubble}
            id={id}
            role="tooltip"
            className="help-bubble"
            style={position}
            onPointerEnter={cancelTimer}
            onPointerLeave={leave}
          >
            {children}
          </div>,
          document.body,
        )}
    </>
  );
}
