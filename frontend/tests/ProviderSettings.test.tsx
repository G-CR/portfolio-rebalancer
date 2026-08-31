import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";

import { createQueryClient } from "../src/app/providers";
import { ProviderSettings } from "../src/features/settings/ProviderSettings";
import { useSaveGeneralSettings, useSaveRebalanceDefaults } from "../src/features/settings/api";
import { emailSettingsFixture, generalSettingsFixture, providerSettingsFixture, rebalanceDefaultsFixture } from "./fixtures";
import { renderWithProviders, server } from "./testProviders";

it("does not expose or submit the deprecated minimum trade amount", async () => {
  let generalSettingsPayload: Record<string, unknown> | null = null;
  renderWithProviders(<ProviderSettings />, {
    handlers: [
      http.get("/api/settings/providers", () => HttpResponse.json(providerSettingsFixture)),
      http.get("/api/settings/general", () => HttpResponse.json(generalSettingsFixture)),
      http.get("/api/settings/email", () => HttpResponse.json(emailSettingsFixture)),
      http.put("/api/settings/general", async ({ request }) => {
        generalSettingsPayload = await request.json() as Record<string, unknown>;
        return HttpResponse.json({ ...generalSettingsFixture, ...generalSettingsPayload });
      }),
    ],
  });
  const user = userEvent.setup();

  expect(await screen.findByRole("heading", { name: "自动刷新与再平衡默认值" })).toBeInTheDocument();
  expect(screen.queryByLabelText("默认最小交易金额")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "保存通用设置" }));

  expect(generalSettingsPayload).not.toHaveProperty("minimum_trade_amount_cny");
});

it("whitelists settings PUT bodies when mutations receive response-shaped objects", async () => {
  let generalSettingsPayload: Record<string, unknown> | null = null;
  let rebalanceDefaultsPayload: Record<string, unknown> | null = null;
  server.use(
    http.put("/api/settings/general", async ({ request }) => {
      generalSettingsPayload = await request.json() as Record<string, unknown>;
      return HttpResponse.json(generalSettingsFixture);
    }),
    http.put("/api/settings/rebalance-defaults", async ({ request }) => {
      rebalanceDefaultsPayload = await request.json() as Record<string, unknown>;
      return HttpResponse.json(rebalanceDefaultsFixture);
    }),
  );
  const queryClient = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  const general = renderHook(() => useSaveGeneralSettings(), { wrapper });
  const rebalance = renderHook(() => useSaveRebalanceDefaults(), { wrapper });
  const generalResponse = { ...generalSettingsFixture, provider_priority: [...generalSettingsFixture.provider_priority], future_response_field: "ignore me" };
  const rebalanceResponse = { ...rebalanceDefaultsFixture, future_response_field: "ignore me" };

  await act(async () => {
    await general.result.current.mutateAsync(generalResponse);
    await rebalance.result.current.mutateAsync(rebalanceResponse);
  });

  expect(generalSettingsPayload).toEqual({
    refresh_time: generalSettingsFixture.refresh_time,
    provider_priority: generalSettingsFixture.provider_priority,
    default_tolerance: generalSettingsFixture.default_tolerance,
    allow_sell: generalSettingsFixture.allow_sell,
    allow_fx: generalSettingsFixture.allow_fx,
  });
  expect(rebalanceDefaultsPayload).toEqual({
    available_cny: rebalanceDefaultsFixture.available_cny,
    available_usd: rebalanceDefaultsFixture.available_usd,
    valuation_basis: rebalanceDefaultsFixture.valuation_basis,
    tolerance: rebalanceDefaultsFixture.tolerance,
    allow_sell: rebalanceDefaultsFixture.allow_sell,
    allow_fx: rebalanceDefaultsFixture.allow_fx,
  });
});
