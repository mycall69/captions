import type { components } from './types.gen';

type ErrorBody = components['schemas']['ErrorBody'];

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly httpStatus: number,
    public readonly requestId: string,
    public readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// next.config.ts에서 /api/v1/* → http://localhost:8000/v1/* 로 프록시
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? '/api/v1';

export async function apiFetch<TData>(path: string, init?: RequestInit): Promise<TData> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
  });

  const body = (await res.json()) as {
    success: boolean;
    data?: TData;
    error?: ErrorBody;
    request_id: string;
  };

  if (!body.success || !res.ok) {
    const err = body.error ?? { code: 'INTERNAL_ERROR', message: 'Unknown error' };
    throw new ApiError(
      err.code,
      err.message,
      res.status,
      body.request_id,
      err.details as Record<string, unknown> | undefined,
    );
  }

  return body.data as TData;
}
