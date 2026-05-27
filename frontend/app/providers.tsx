/**
 * Providers — Client side context provider 묶음 (T110)
 *
 * TanStack Query QueryClientProvider 를 글로벌로 노출하여 useJob / useJobWithEvents 등이
 * 동작하도록 한다.
 */
'use client';
import * as React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

export function Providers({ children }: { children: React.ReactNode }) {
  // QueryClient 는 첫 render 시 1회 생성. SSR 마다 새로 만드는 것을 피한다.
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
