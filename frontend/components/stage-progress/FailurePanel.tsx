/**
 * FailurePanel — 작업 실패 패널 (T107, US2)
 *
 * 와이어프레임 §S2 실패 시 패널:
 *   ❌ 실패: 자막을 찾을 수 없습니다
 *      이 영상에는 한국어 / 일본어 자막이 없습니다.
 *      향후 음성 인식(STT) 지원이 추가될 예정입니다.
 *
 *      실패 단계: subtitle_processing
 *      발생 시각: 09:31:22
 *
 *      [ 새 영상으로 다시 시도 ]   [ 동일 URL 재시도 ]
 *
 * 헌법 V — 한국어 라벨 / 한국어 주석. 사용자 노출 텍스트는 서버 제공 한국어 메시지를 우선 사용.
 */
'use client';
import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { STAGE_LABEL_KO, type JobStatus } from '@/lib/i18n/jobLabels';

// error_code → 사용자 친화적 부제 (서버가 error_message 를 한국어로 제공하지만,
// 코드 기반 보조 라벨이 일관된 톤으로 유용함).
const ERROR_CODE_LABEL: Record<string, string> = {
  USER_CANCELLED: '사용자 취소',
  SUBTITLE_NOT_FOUND: '자막을 찾을 수 없음',
  SUBTITLE_LANGUAGE_UNSUPPORTED: '지원하지 않는 자막 언어',
  TRANSLATION_FAILED: '번역 실패',
  DOWNLOAD_FAILED: '다운로드 실패',
  RENDER_FAILED: '렌더링 실패',
  INTERNAL_ERROR: '내부 오류',
};

interface FailurePanelProps {
  errorStage?: string | null;
  errorCode?: string | null;
  errorMessage?: string | null;
  /** 실패 시각 ISO-8601. 비어 있으면 표시하지 않음. */
  failedAt?: string | null;
  /** 원본 영상 URL — "동일 URL 재시도" 액션에서 사용. */
  sourceUrl?: string | null;
  className?: string;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString('ko-KR', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return iso;
  }
}

export function FailurePanel({
  errorStage,
  errorCode,
  errorMessage,
  failedAt,
  sourceUrl,
  className,
}: FailurePanelProps) {
  const router = useRouter();

  const headline =
    (errorCode && ERROR_CODE_LABEL[errorCode]) ?? '작업이 실패했습니다';
  const stageLabel = errorStage
    ? STAGE_LABEL_KO[errorStage as JobStatus] ?? errorStage
    : null;

  // "다시 시도" — 동일 URL 을 querystring 으로 prefill 하여 메인(S1)으로 이동.
  // 자동 재제출은 사용자 의도(이중 비용)를 명시적으로 확인해야 하므로 prefill 만 수행한다.
  const handleRetry = React.useCallback(() => {
    if (sourceUrl) {
      const q = new URLSearchParams({ url: sourceUrl }).toString();
      router.push(`/?${q}`);
    } else {
      router.push('/');
    }
  }, [router, sourceUrl]);

  const handleHome = React.useCallback(() => {
    router.push('/');
  }, [router]);

  return (
    <Card
      data-testid="failure-panel"
      role="alert"
      className={cn(
        'border-destructive/40 bg-destructive/5 text-foreground',
        className,
      )}
    >
      <CardContent className="space-y-4 p-6">
        <div className="flex items-start gap-3">
          <span aria-hidden className="text-2xl">❌</span>
          <div className="space-y-1">
            <h2 className="text-lg font-semibold text-destructive">
              실패: {headline}
            </h2>
            {errorMessage && (
              <p data-testid="failure-message" className="text-sm">
                {errorMessage}
              </p>
            )}
          </div>
        </div>

        <dl className="space-y-1 text-sm text-muted-foreground">
          {stageLabel && (
            <div className="flex gap-2">
              <dt className="w-24 font-medium">실패 단계:</dt>
              <dd data-testid="failure-stage">{stageLabel}</dd>
            </div>
          )}
          {errorCode && (
            <div className="flex gap-2">
              <dt className="w-24 font-medium">오류 코드:</dt>
              <dd data-testid="failure-code" className="font-mono text-xs">
                {errorCode}
              </dd>
            </div>
          )}
          {failedAt && (
            <div className="flex gap-2">
              <dt className="w-24 font-medium">발생 시각:</dt>
              <dd>{formatTime(failedAt)}</dd>
            </div>
          )}
        </dl>

        <div className="flex flex-wrap gap-2 pt-2">
          {sourceUrl && (
            <Button
              type="button"
              variant="default"
              onClick={handleRetry}
              data-testid="failure-retry"
            >
              동일 URL 재시도
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            onClick={handleHome}
            data-testid="failure-home"
          >
            새 영상으로 다시 시도
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
