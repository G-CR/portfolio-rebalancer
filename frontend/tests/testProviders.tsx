import { QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { setupServer } from "msw/node";
import type { RequestHandler } from "msw";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { createQueryClient } from "../src/app/providers";

export const server = setupServer();

type TestProviderOptions = Omit<RenderOptions, "wrapper"> & {
  route?: string;
  handlers?: RequestHandler[];
};

export function renderWithProviders(
  ui: ReactElement,
  { route = "/", handlers = [], ...renderOptions }: TestProviderOptions = {},
) {
  const queryClient = createQueryClient();
  server.use(...handlers);

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }

  return {
    queryClient,
    ...render(ui, { wrapper: Wrapper, ...renderOptions }),
  };
}
