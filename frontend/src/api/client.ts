import type { ApiErrorDetail } from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: ApiErrorDetail;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message);
    this.name = "ApiError";
    this.status = status;
    this.code = detail.code;
    this.detail = detail;
  }
}

function validationMessage(detail: unknown) {
  if (!Array.isArray(detail)) return null;
  return detail
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const candidate = item as { loc?: unknown[]; msg?: unknown };
      const field = candidate.loc?.filter((part) => part !== "body").join(".");
      return [field, candidate.msg].filter(Boolean).join(": ");
    })
    .filter(Boolean)
    .join("; ");
}

async function errorDetail(response: Response): Promise<ApiErrorDetail> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return { code: "HTTP_ERROR", message: `Request failed with status ${response.status}.` };
  }

  const rawDetail = body && typeof body === "object" && "detail" in body
    ? (body as { detail: unknown }).detail
    : body;

  if (rawDetail && typeof rawDetail === "object" && !Array.isArray(rawDetail)) {
    const detail = rawDetail as Record<string, unknown>;
    return {
      ...detail,
      code: typeof detail.code === "string" ? detail.code : "HTTP_ERROR",
      message: typeof detail.message === "string"
        ? detail.message
        : `Request failed with status ${response.status}.`,
    } as ApiErrorDetail;
  }

  return {
    code: "VALIDATION_ERROR",
    message: validationMessage(rawDetail) || `Request failed with status ${response.status}.`,
    errors: rawDetail,
  };
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function jsonBody(value: unknown) {
  return JSON.stringify(value);
}
