import { Menu, RefreshCw, Save, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { APP_ROUTES } from "../../app/navigation";
import styles from "./AppShell.module.css";

const MOBILE_NAVIGATION_QUERY = "(max-width: 760px)";
const focusableSelector = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function currentRoute(pathname: string) {
  return APP_ROUTES.find((route) => route.path === pathname) ?? APP_ROUTES[0];
}

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() =>
    typeof window === "undefined" || typeof window.matchMedia !== "function"
      ? false
      : window.matchMedia(query).matches,
  );

  useEffect(() => {
    const mediaQuery = window.matchMedia(query);
    const updateMatch = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(mediaQuery.matches);
    mediaQuery.addEventListener("change", updateMatch);
    return () => mediaQuery.removeEventListener("change", updateMatch);
  }, [query]);

  return matches;
}

export function AppShell() {
  const location = useLocation();
  const isMobileNavigation = useMediaQuery(MOBILE_NAVIGATION_QUERY);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const navigationRef = useRef<HTMLElement>(null);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const restoreMenuFocus = useRef(true);
  const route = currentRoute(location.pathname);
  const modalNavigationOpen = isMobileNavigation && navigationOpen;

  const closeNavigation = useCallback((restoreFocus = true) => {
    restoreMenuFocus.current = restoreFocus;
    setNavigationOpen(false);
  }, []);

  useEffect(() => {
    if (!modalNavigationOpen) return;

    const navigation = navigationRef.current;
    navigation?.querySelector<HTMLElement>("nav a[href]")?.focus();

    function containNavigationFocus(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeNavigation();
        return;
      }
      if (event.key !== "Tab" || !navigation) return;

      const focusable = Array.from(
        navigation.querySelectorAll<HTMLElement>(focusableSelector),
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!navigation.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", containNavigationFocus);
    return () => {
      document.removeEventListener("keydown", containNavigationFocus);
      const remainsMobile = window.matchMedia(MOBILE_NAVIGATION_QUERY).matches;
      if (restoreMenuFocus.current && remainsMobile) menuTriggerRef.current?.focus();
    };
  }, [closeNavigation, modalNavigationOpen]);

  useEffect(() => {
    if (!isMobileNavigation && navigationOpen) {
      navigationRef.current?.querySelector<HTMLElement>("nav a[href]")?.focus();
      closeNavigation(false);
    }
  }, [closeNavigation, isMobileNavigation, navigationOpen]);

  return (
    <div className={styles.shell}>
      {modalNavigationOpen ? (
        <button
          className={styles.backdrop}
          type="button"
          aria-hidden="true"
          tabIndex={-1}
          data-open="true"
          onClick={() => closeNavigation()}
        />
      ) : null}

      <aside
        ref={navigationRef}
        className={styles.sidebar}
        data-open={modalNavigationOpen}
        aria-label="主导航"
        role={modalNavigationOpen ? "dialog" : undefined}
        aria-modal={modalNavigationOpen ? true : undefined}
      >
        <div className={styles.brand}>
          <span className={styles.brandMark} aria-hidden="true">±</span>
          <span className={styles.brandText}>组合校准台</span>
          {modalNavigationOpen ? (
            <button
              className={styles.mobileCloseButton}
              type="button"
              aria-label="关闭导航"
              onClick={() => closeNavigation()}
            >
              <X size={18} aria-hidden="true" />
            </button>
          ) : null}
        </div>
        <nav className={styles.navigation}>
          {APP_ROUTES.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              end={path === "/"}
              title={label}
              aria-label={label}
              className={({ isActive }) =>
                `${styles.navigationLink} ${isActive ? styles.navigationLinkActive : ""}`
              }
              onClick={() => closeNavigation()}
            >
              <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className={styles.systemStatus}>
          <span className={styles.statusDot} aria-hidden="true" />
          <span className={styles.statusCopy}>
            <strong>本机服务正常</strong>
            <small>未连接外部账户</small>
          </span>
        </div>
      </aside>

      <header
        className={styles.topbar}
        aria-hidden={modalNavigationOpen ? true : undefined}
        inert={modalNavigationOpen ? true : undefined}
      >
        <div className={styles.titleGroup}>
          <button
            ref={menuTriggerRef}
            className={styles.menuButton}
            type="button"
            aria-label="打开导航"
            aria-expanded={modalNavigationOpen}
            onClick={() => {
              if (!isMobileNavigation) return;
              restoreMenuFocus.current = true;
              setNavigationOpen(true);
            }}
          >
            <Menu size={19} aria-hidden="true" />
          </button>
          <div>
            <p className={styles.context}>核心资产池</p>
            <h1>{route.label}</h1>
          </div>
        </div>
        <div className={styles.topbarCommands}>
          <div className={styles.dataTime}>
            <span>最近市场数据</span>
            <strong>尚未刷新</strong>
          </div>
          <button className={styles.commandButton} type="button" title="刷新市场数据">
            <RefreshCw size={16} aria-hidden="true" />
            <span>刷新</span>
          </button>
          <button className={styles.primaryCommand} type="button" title="保存当前快照">
            <Save size={16} aria-hidden="true" />
            <span>保存快照</span>
          </button>
        </div>
      </header>

      <main
        className={styles.main}
        aria-hidden={modalNavigationOpen ? true : undefined}
        inert={modalNavigationOpen ? true : undefined}
      >
        <Outlet />
      </main>
    </div>
  );
}
