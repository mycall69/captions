'use client';

// T028 참고: sonner 패키지는 Phase 1 package.json에 포함되지 않음.
// Phase 6 (T122)에서 sonner를 추가할 예정이므로 현재는 플레이스홀더를 제공한다.
// 실제 사용 시: npm install sonner 후 아래 주석을 해제하고 플레이스홀더를 제거한다.

// import { Toaster as SonnerToaster } from 'sonner';
// export function Toaster() { return <SonnerToaster theme="dark" richColors />; }

export function Toaster() {
  return null; // Phase 6 (T122)에서 sonner 토스트로 교체 예정
}
