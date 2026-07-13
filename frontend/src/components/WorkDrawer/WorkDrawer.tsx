import { X } from "lucide-react";
import { useEffect, useId, useRef, type PropsWithChildren } from "react";
import { createPortal } from "react-dom";

import { canRestoreFocus, isTopDrawer, registerDrawer } from "./drawerStack";

type WorkDrawerProps = PropsWithChildren<{
  open: boolean;
  title: string;
  onClose: () => void;
  footer?: React.ReactNode;
}>;

export function WorkDrawer({ open, title, onClose, footer, children }: WorkDrawerProps) {
  const reactId = useId();
  const drawerId = `work-drawer-${reactId.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const titleId = `${drawerId}-title`;
  const layerRef = useRef<HTMLDivElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement as HTMLElement | null;
    const layer = layerRef.current;
    const drawer = drawerRef.current;
    if (!layer || !drawer) return;

    const unregister = registerDrawer({
      id: drawerId,
      layer,
      panel: drawer,
      close: () => onCloseRef.current(),
    });

    return () => {
      unregister();
      if (canRestoreFocus(previousFocus.current)) previousFocus.current?.focus();
    };
  }, [drawerId, open]);

  if (!open) return null;

  return createPortal(
    <div ref={layerRef} className="work-drawer-layer" data-work-drawer-layer={drawerId}>
      <div
        className="work-drawer-backdrop"
        aria-hidden="true"
        onClick={() => {
          if (isTopDrawer(drawerId)) onCloseRef.current();
        }}
      />
      <section
        ref={drawerRef}
        className="work-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="work-drawer__header">
          <h2 id={titleId}>{title}</h2>
          <button
            className="work-drawer__close"
            type="button"
            aria-label="关闭工作抽屉"
            onClick={() => {
              if (isTopDrawer(drawerId)) onCloseRef.current();
            }}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="work-drawer__body">{children}</div>
        {footer ? <footer className="work-drawer__footer">{footer}</footer> : null}
      </section>
    </div>,
    document.body,
  );
}
