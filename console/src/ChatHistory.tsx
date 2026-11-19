import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { chatScroll } from "./chat-scroll.ts";

export function ChatHistory({
  children,
  version,
}: {
  children: ReactNode;
  version: unknown;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const controller = useRef<ReturnType<typeof chatScroll> | null>(null);
  const [showJump, setShowJump] = useState(false);

  useLayoutEffect(() => {
    const area = viewport.current!;
    const scroll = chatScroll(area, setShowJump);
    controller.current = scroll;
    area.addEventListener("scroll", scroll.onScroll, { passive: true });
    const observer = new ResizeObserver(scroll.changed);
    observer.observe(area);
    observer.observe(content.current!);
    scroll.changed();
    return () => {
      observer.disconnect();
      area.removeEventListener("scroll", scroll.onScroll);
      controller.current = null;
    };
  }, []);

  useLayoutEffect(() => controller.current?.changed(), [version]);

  return (
    <div className="direct-history">
      <div
        className="direct-messages"
        role="region"
        aria-label="Chat history"
        tabIndex={0}
        ref={viewport}
      >
        <div className="chat-messages direct-message-list" ref={content}>
          {children}
        </div>
      </div>
      <div className="chat-scroll-controls">
        {showJump && (
          <button
            className="secondary jump-to-latest"
            type="button"
            onClick={() => {
              controller.current?.jump();
              viewport.current?.focus({ preventScroll: true });
            }}
          >
            Jump to latest ↓
          </button>
        )}
      </div>
    </div>
  );
}
