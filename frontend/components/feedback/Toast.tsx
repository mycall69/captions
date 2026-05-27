/**
 * T122: 토스트 알림 컴포넌트.
 *
 * - shadcn `sonner` 패키지가 아직 설치되지 않아 (T028 placeholder) Radix `react-toast`
 *   기반의 경량 토스트 시스템을 직접 구현한다.
 * - 외부 호출 시그니처는 sonner 와 호환: `toast({title, description, variant})`.
 * - `<ToastProvider>` 를 앱 루트(예: `app/layout.tsx`) 에 마운트해야 한다.
 *
 * 헌법 V — 사용자 노출 텍스트는 한국어. 본 컴포넌트는 라이브러리이므로 문구는
 * 호출자가 한국어로 제공한다.
 */
'use client';

import * as RadixToast from '@radix-ui/react-toast';
import * as React from 'react';

import { cn } from '@/lib/utils';

// ── 외부 API 타입 ───────────────────────────────────────────────────────────

export type ToastVariant = 'default' | 'success' | 'destructive';

export interface ToastOptions {
  /** 한국어 제목. */
  title: string;
  /** 보조 설명 (옵션). */
  description?: string;
  /** 시각 variant — 기본 `default`. */
  variant?: ToastVariant;
  /** 자동 닫힘까지의 ms (Radix 기본 5000). */
  duration?: number;
}

// 내부 toast id 시퀀스.
type ToastRecord = ToastOptions & { id: number };

// ── 글로벌 store (간단한 pub/sub) ────────────────────────────────────────────

type Listener = (records: ToastRecord[]) => void;

class ToastStore {
  private records: ToastRecord[] = [];
  private listeners = new Set<Listener>();
  private nextId = 1;

  push(opts: ToastOptions): number {
    const record: ToastRecord = { ...opts, id: this.nextId++ };
    this.records = [...this.records, record];
    this.notify();
    return record.id;
  }

  dismiss(id: number): void {
    this.records = this.records.filter((r) => r.id !== id);
    this.notify();
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    fn(this.records);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private notify(): void {
    for (const fn of this.listeners) {
      fn(this.records);
    }
  }
}

const _store = new ToastStore();

/**
 * 토스트를 표시한다. sonner 와 시그니처 호환.
 *
 * 예: `toast({title: '저장됨', variant: 'success'})`
 */
export function toast(opts: ToastOptions): number {
  return _store.push(opts);
}

toast.dismiss = (id: number): void => _store.dismiss(id);

// ── 시각 variant → Tailwind 매핑 ────────────────────────────────────────────

const _variantClass: Record<ToastVariant, string> = {
  default: 'border-slate-700 bg-slate-900 text-slate-100',
  success: 'border-emerald-700 bg-emerald-950 text-emerald-100',
  destructive: 'border-red-700 bg-red-950 text-red-100',
};

// ── Provider 컴포넌트 ───────────────────────────────────────────────────────

/**
 * Radix Toast viewport 를 마운트한다. 앱 layout 의 children 뒤에 배치하면 된다.
 *
 * 예: `<body>{children}<ToastProvider /></body>`
 */
export function ToastProvider(): React.ReactElement {
  const [records, setRecords] = React.useState<ToastRecord[]>([]);

  React.useEffect(() => _store.subscribe(setRecords), []);

  return (
    <RadixToast.Provider swipeDirection="right">
      {records.map((r) => (
        <RadixToast.Root
          key={r.id}
          duration={r.duration}
          onOpenChange={(open) => {
            if (!open) {
              _store.dismiss(r.id);
            }
          }}
          className={cn(
            'pointer-events-auto flex w-full max-w-sm flex-col gap-1 rounded-lg border px-4 py-3 shadow-lg',
            _variantClass[r.variant ?? 'default'],
          )}
        >
          <RadixToast.Title className="text-sm font-semibold">{r.title}</RadixToast.Title>
          {r.description ? (
            <RadixToast.Description className="text-xs opacity-90">
              {r.description}
            </RadixToast.Description>
          ) : null}
        </RadixToast.Root>
      ))}
      <RadixToast.Viewport
        className="fixed bottom-4 right-4 z-[100] flex max-h-screen w-full max-w-sm flex-col gap-2 outline-none"
        aria-label="알림 영역"
      />
    </RadixToast.Provider>
  );
}

// 테스트 / 디버깅용 — 외부에서 store 를 들여다볼 일은 없도록 export 하지 않는다.
