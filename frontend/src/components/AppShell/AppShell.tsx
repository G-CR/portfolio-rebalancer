import { Menu, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { APP_ROUTES } from "../../app/navigation";
import type { MarketDataStatus } from "../../api/types";
import { formatDataTime } from "../../features/analytics/format";
import { useMarketData, useRefreshMarketData } from "../../features/marketData/api";
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

function marketStatusSummary(items: MarketDataStatus[] | undefined) {
  if (!items) return { label: "\u5c1a\u672a\u5237\u65b0", tone: "unknown" };
  if (items.length === 0) return { label: "尚无市场数据", tone: "unknown" };
  if (items.some((item) => item.status === "missing" || item.status === "failed")) {
    return { label: "\u6570\u636e\u9700\u5904\u7406", tone: "attention" };
  }
  if (items.some((item) => item.status === "stale")) {
    return { label: "\u6570\u636e\u5df2\u8fc7\u671f", tone: "stale" };
  }
  if (items.some((item) => item.status === "manual")) {
    return { label: "\u5305\u542b\u624b\u52a8\u503c", tone: "manual" };
  }
  return { label: "\u6570\u636e\u6709\u6548", tone: "valid" };
}

function latestMarketTime(items: MarketDataStatus[] | undefined) {
  return items
    ?.flatMap((item) => item.market_time ? [item.market_time] : [])
    .sort()
    .at(-1) ?? null;
}

export function AppShell() {
  const location = useLocation();
  const isMobileNavigation = useMediaQuery(MOBILE_NAVIGATION_QUERY);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const navigationRef = useRef<HTMLElement>(null);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const restoreMenuFocus = useRef(true);
  const marketData = useMarketData();
  const refreshMarketData = useRefreshMarketData();
  const [refreshFailed, setRefreshFailed] = useState(false);
  const route = currentRoute(location.pathname);
  const modalNavigationOpen = isMobileNavigation && navigationOpen;
  const status = marketStatusSummary(marketData.data?.items);
  const mostRecentMarketTime = latestMarketTime(marketData.data?.items);

  const refresh = useCallback(async () => {
    setRefreshFailed(false);
    try {
      await refreshMarketData.mutateAsync();
    } catch {
      setRefreshFailed(true);
    }
  }, [refreshMarketData]);

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
          <div className={styles.dataTime} data-status={status.tone}>
            <span>最近市场数据</span>
            <strong>{mostRecentMarketTime ? formatDataTime(mostRecentMarketTime) : status.label}</strong>
            <small>{mostRecentMarketTime ? status.label : null}</small>
          </div>
          <button
            className={styles.commandButton}
            type="button"
            title="刷新市场数据"
            disabled={refreshMarketData.isPending}
            onClick={() => void refresh()}
          >
            <RefreshCw size={16} aria-hidden="true" />
            <span>{refreshMarketData.isPending ? "正在刷新" : "刷新"}</span>
          </button>
        </div>
        {refreshFailed ? (
          <div className={styles.refreshAlert} role="alert">
            <span>刷新失败，已保留当前市场数据。</span>
            <NavLink to="/data-sources">查看数据源</NavLink>
          </div>
        ) : null}
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
