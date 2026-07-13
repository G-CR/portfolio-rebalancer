import { X } from "lucide-react";
import { useEffect, useRef, type PropsWithChildren } from "react";
import { createPortal } from "react-dom";

import { canRestoreFocus, isTopDrawer, registerDrawer } from "./drawerStack";

type WorkDrawerProps = PropsWithChildren<{
  open: boolean;
  title: string;
  onClose: () => void;
  footer?: React.ReactNode;
}>;

let nextDrawerDomId = 0;

function allocateDrawerDomId() {
  nextDrawerDomId += 1;
  return `work-drawer-${nextDrawerDomId}`;
}

export function WorkDrawer({ open, title, onClose, footer, children }: WorkDrawerProps) {
  const identityRef = useRef<object | null>(null);
  const domIdRef = useRef<string | null>(null);
  if (identityRef.current === null) identityRef.current = {};
  if (domIdRef.current === null) domIdRef.current = allocateDrawerDomId();
  const drawerIdentity = identityRef.current;
  const drawerDomId = domIdRef.current;
  const titleId = `${drawerDomId}-title`;
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
      identity: drawerIdentity,
      layer,
      panel: drawer,
      close: () => onCloseRef.current(),
    });

    return () => {
      unregister();
      if (canRestoreFocus(previousFocus.current)) previousFocus.current?.focus();
    };
  }, [drawerIdentity, open]);

  if (!open) return null;

  return createPortal(
    <div ref={layerRef} className="work-drawer-layer" data-work-drawer-layer={drawerDomId}>
      <div
        className="work-drawer-backdrop"
        aria-hidden="true"
        onClick={() => {
          if (isTopDrawer(drawerIdentity)) onCloseRef.current();
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
              if (isTopDrawer(drawerIdentity)) onCloseRef.current();
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
