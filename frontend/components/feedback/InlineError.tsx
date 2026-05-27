/**
 * T122: 폼/카드 내부에 인라인으로 표시하는 오류 메시지.
 *
 * - 사용자 노출 메시지는 한국어 (헌법 V). 호출자가 한국어 문자열을 제공한다.
 * - `code` 는 디버깅 / e2e 추적용 (예: `INVALID_URL`) — 화면 우측에 작게 표기.
 * - shadcn-style: 빨간 테두리 + 어두운 배경 + 빨간 텍스트.
 *
 * 사용 예::
 *
 *     <InlineError message="유효한 YouTube URL 을 입력해 주세요." code="INVALID_URL" />
 */
'use client';

import { AlertCircle } from 'lucide-react';
import * as React from 'react';

import { cn } from '@/lib/utils';

export interface InlineErrorProps {
  /** 한국어 메시지 본문. */
  message: string;
  /** 기계 판독용 에러 코드 (옵션). */
  code?: string;
  /** 추가 클래스. */
  className?: string;
}

export function InlineError({ message, code, className }: InlineErrorProps): React.ReactElement {
  return (
    <div
      role="alert"
      data-testid="inline-error"
      data-error-code={code ?? undefined}
      className={cn(
        'flex items-start gap-2 rounded-md border border-red-500 bg-red-50/10 px-3 py-2 text-sm text-red-200',
        className,
      )}
    >
      <AlertCircle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
      <p className="flex-1 leading-snug">{message}</p>
      {code ? (
        <span className="shrink-0 self-start font-mono text-xs uppercase text-red-300/80">
          {code}
        </span>
      ) : null}
    </div>
  );
}
