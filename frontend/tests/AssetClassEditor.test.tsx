import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";

import { AssetClassesPage } from "../src/pages/AssetClassesPage";
import { holdingsQueryKey } from "../src/features/holdings/api";
import { assetClassFixtures } from "./fixtures";
import { renderWithProviders } from "./testProviders";

afterEach(() => vi.restoreAllMocks());

const holdingsHandler = http.get("/api/holdings", () => HttpResponse.json([]));

describe("AssetClassEditor", () => {
  it("blocks saving and explains an exact deficit", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AssetClassesPage />, {
      handlers: [
        http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
        holdingsHandler,
      ],
    });

    const input = await screen.findByRole("textbox", { name: "红利低波目标比例" });
    await user.clear(input);
    await user.type(input, "10");

    expect(screen.getByText("还差 10.0% 才达到 100%" )).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存资产配置" })).toBeDisabled();
  });

  it("explains excess and submits exact decimal strings", async () => {
    const user = userEvent.setup();
    let requestBody: unknown;
    const { queryClient } = renderWithProviders(<AssetClassesPage />, {
      handlers: [
        http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
        holdingsHandler,
        http.put("/api/asset-classes", async ({ request }) => {
          requestBody = await request.json();
          return HttpResponse.json(assetClassFixtures);
        }),
      ],
    });
    queryClient.setQueryData(holdingsQueryKey(false), []);

    const input = await screen.findByRole("textbox", { name: "红利低波目标比例" });
    await user.clear(input);
    await user.type(input, "30.00000001");
    expect(screen.getByText("超出 10.00000001%，请调减至 100%" )).toBeInTheDocument();

    await user.clear(input);
    await user.type(input, "20.00000000");
    await user.click(screen.getByRole("button", { name: "保存资产配置" }));

    await waitFor(() => expect(requestBody).toBeDefined());
    expect((requestBody as Array<{ target_weight: string }>)[0].target_weight)
      .toBe("0.20000000");
    expect(screen.getByText("资产配置已保存")).toBeInTheDocument();
    expect(queryClient.getQueryState(holdingsQueryKey(false))?.isInvalidated).toBe(true);
  });

  it("surfaces a structured backend save error and keeps edits", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AssetClassesPage />, {
      handlers: [
        http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
        holdingsHandler,
        http.put("/api/asset-classes", () => HttpResponse.json({
          detail: {
            code: "ASSET_CLASS_NAME_CONFLICT",
            message: "Active asset class names must be unique.",
          },
        }, { status: 409 })),
      ],
    });

    const note = await screen.findByRole("textbox", { name: "红利低波备注" });
    await user.type(note, "长期核心仓位");
    await user.click(screen.getByRole("button", { name: "保存资产配置" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Active asset class names must be unique.",
    );
    expect(note).toHaveValue("长期核心仓位");
  });

  it("cancels and confirms deactivation with an explicit holding impact warning", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderWithProviders(<AssetClassesPage />, {
      handlers: [
        http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
        http.get("/api/holdings", () => HttpResponse.json([{
          id: "holding-spy",
          asset_class_id: assetClassFixtures[2].id,
          is_active: true,
        }])),
      ],
    });

    const active = await screen.findByRole("checkbox", { name: "标普 500启用状态" });
    await user.click(active);
    expect(active).toBeChecked();
    expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining("1 个关联持仓"));

    await user.click(active);
    expect(active).not.toBeChecked();
    expect(screen.getByText("还差 30.0% 才达到 100%" )).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存资产配置" })).toBeDisabled();
  });

  it("submits inactive rows with preserved data after active weights return to 100%", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let body: unknown;
    renderWithProviders(<AssetClassesPage />, {
      handlers: [
        http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
        holdingsHandler,
        http.put("/api/asset-classes", async ({ request }) => {
          body = await request.json();
          return HttpResponse.json(body as Record<string, unknown>[]);
        }),
      ],
    });

    await user.click(await screen.findByRole("checkbox", { name: "标普 500启用状态" }));
    const target = screen.getByRole("textbox", { name: "红利低波目标比例" });
    await user.clear(target);
    await user.type(target, "50");
    await user.click(screen.getByRole("button", { name: "保存资产配置" }));

    await waitFor(() => expect(body).toBeDefined());
    const submitted = body as Array<{ id: string; target_weight: string; is_active: boolean }>;
    expect(submitted).toHaveLength(5);
    expect(submitted.find((item) => item.id === assetClassFixtures[2].id)).toMatchObject({
      is_active: false,
      target_weight: "0.30000000",
    });
  });
});
