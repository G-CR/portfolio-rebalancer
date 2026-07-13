import React from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { AppShell } from "../components/AppShell/AppShell";
import { AssetClassesPage } from "../pages/AssetClassesPage";
import { DashboardPage } from "../pages/DashboardPage";
import { HoldingsPage } from "../pages/HoldingsPage";
import { PnlPage } from "../pages/PnlPage";
import { APP_ROUTES } from "./navigation";

// The production container currently compiles JSX in classic mode.
(globalThis as typeof globalThis & { React?: typeof React }).React ??= React;

function RouteWorkspace({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <section className="route-workspace" aria-labelledby="workspace-title">
      <header className="route-workspace__header">
        <div>
          <p className="route-workspace__eyebrow">组合维护工作区</p>
          <h2 id="workspace-title">{title}</h2>
          <p>{description}</p>
        </div>
        <p className="route-workspace__state">工作区已就绪</p>
      </header>
      <div className="route-workspace__body">
        <div className="route-workspace__primary">
          <p className="route-workspace__label">主要工作区</p>
          <div className="route-workspace__placeholder">等待载入组合数据</div>
        </div>
        <aside className="route-workspace__secondary" aria-label="页面状态">
          <p className="route-workspace__label">数据口径</p>
          <p>所有金额以人民币汇总，比例按最近有效市场数据计算。</p>
        </aside>
      </div>
    </section>
  );
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: APP_ROUTES.map((route) => {
      const element = route.path === "/"
        ? <DashboardPage />
        : route.path === "/allocation"
          ? <AssetClassesPage />
          : route.path === "/holdings"
            ? <HoldingsPage />
            : route.path === "/analysis"
              ? <PnlPage />
              : <RouteWorkspace title={route.label} description={route.description} />;
      return {
        index: route.path === "/" ? true : undefined,
        path: route.path === "/" ? undefined : route.path.slice(1),
        element,
      };
    }),
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
