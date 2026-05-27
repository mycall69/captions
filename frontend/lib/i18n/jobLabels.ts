/**
 * jobLabels — 작업 상태(JobStatus) 의 한국어 라벨 단일 출처.
 *
 * 와이어프레임 §S2 단계 진행 노드명을 정본으로 삼는다.
 * 자막 처리 단계는 "자막 추출" 이 아닌 "자막 처리" 로 통일 (wireframes.md:136 참조).
 *
 * - STAGE_LABEL_KO     : StageProgressBar / StageLog / FailurePanel 등에서 단계 명사 표기.
 * - STATUS_BADGE_LABEL_KO : StatusBadge 처럼 "진행 중" 어미를 붙여 현재 상태를 알리는 표기.
 *
 * 헌법 V — 사용자 노출 텍스트는 한국어, 식별자(JobStatus)는 영문 토큰을 유지한다.
 */
import type { components } from '@/lib/api/types.gen';

export type JobStatus = components['schemas']['JobStatus'];

/** 단계 명사형 라벨 — 단계 진행 노드, 로그 행, 실패 단계 표기 등에서 사용. */
export const STAGE_LABEL_KO: Record<JobStatus, string> = {
  pending: '대기',
  downloading: '다운로드',
  subtitle_processing: '자막 처리',
  translating: '번역',
  rendering: '렌더링',
  completed: '완료',
  failed: '실패',
};

/** 진행 상태 어미형 라벨 — StatusBadge 등 "현재 상태" 표시용. */
export const STATUS_BADGE_LABEL_KO: Record<JobStatus, string> = {
  pending: '대기 중',
  downloading: '다운로드 중',
  subtitle_processing: '자막 처리 중',
  translating: '번역 중',
  rendering: '렌더링 중',
  completed: '완료',
  failed: '실패',
};
