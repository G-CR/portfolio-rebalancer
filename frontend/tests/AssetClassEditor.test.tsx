import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";

import { AssetClassesPage } from "../src/pages/AssetClassesPage";
import { assetClassFixtures } from "./fixtures";
import { renderWithProviders } from "./testProviders";

describe("AssetClassEditor", () => {
  it("blocks saving and explains an exact deficit", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AssetClassesPage />, {
      handlers: [
        http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
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
    renderWithProviders(<AssetClassesPage />, {
      handlers: [
        http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
        http.put("/api/asset-classes", async ({ request }) => {
          requestBody = await request.json();
          return HttpResponse.json(assetClassFixtures);
        }),
      ],
    });

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
  });

  it("surfaces a structured backend save error and keeps edits", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AssetClassesPage />, {
      handlers: [
        http.get("/api/asset-classes", () => HttpResponse.json(assetClassFixtures)),
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
});
