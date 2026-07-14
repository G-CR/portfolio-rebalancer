import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";

import { server } from "./testProviders";

let interceptedFetch: typeof fetch;

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
  interceptedFetch = globalThis.fetch;
  globalThis.fetch = (input, init) => {
    const signal = init?.signal;
    if (!signal) return interceptedFetch(input, init);

    const request = interceptedFetch(input, { ...init, signal: undefined });
    if (signal.aborted) return Promise.reject(signal.reason);
    return new Promise<Response>((resolve, reject) => {
      const abort = () => reject(signal.reason);
      signal.addEventListener("abort", abort, { once: true });
      void request.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
    });
  };
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => {
  globalThis.fetch = interceptedFetch;
  server.close();
});
