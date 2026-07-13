import { Menu, RefreshCw, Save, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { APP_ROUTES } from "../../app/navigation";
import styles from "./AppShell.module.css";

function currentRoute(pathname: string) {
  return APP_ROUTES.find((route) => route.path === pathname) ?? APP_ROUTES[0];
}

export function AppShell() {
  const location = useLocation();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const route = currentRoute(location.pathname);

  useEffect(() => {
    if (!navigationOpen) return;

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setNavigationOpen(false);
    }

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [navigationOpen]);

  return (
    <div className={styles.shell}>
      <button
        className={styles.backdrop}
        type="button"
        aria-label="关闭导航"
        aria-hidden={!navigationOpen}
        tabIndex={navigationOpen ? 0 : -1}
        data-open={navigationOpen}
        onClick={() => setNavigationOpen(false)}
      />

      <aside className={styles.sidebar} data-open={navigationOpen} aria-label="主导航">
        <div className={styles.brand}>
          <span className={styles.brandMark} aria-hidden="true">±</span>
          <span className={styles.brandText}>组合校准台</span>
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
              onClick={() => setNavigationOpen(false)}
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

      <header className={styles.topbar}>
        <div className={styles.titleGroup}>
          <button
            className={styles.menuButton}
            type="button"
            aria-label={navigationOpen ? "关闭导航" : "打开导航"}
            aria-expanded={navigationOpen}
            onClick={() => setNavigationOpen((open) => !open)}
          >
            {navigationOpen ? <X size={19} /> : <Menu size={19} />}
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

      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
