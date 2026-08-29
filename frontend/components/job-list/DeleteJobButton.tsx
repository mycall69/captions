/**
 * DeleteJobButton — 종결 작업(completed/failed) 영구 삭제 트리거 (FR-030a).
 *
 * JobListItem 에서 종결 상태일 때만 렌더하므로, 비종결 항목은 본 모듈을 import 하지
 * 않아 useDeleteJob mutation hook (TanStack Query) 호출이 발생하지 않는다.
 * 헌법 V — 한국어 문구.
 */
'use client';
import * as React from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useDeleteJob } from '@/lib/api/hooks';

interface DeleteJobButtonProps {
  jobId: string;
  jobTitle: string;
}

export function DeleteJobButton({ jobId, jobTitle }: DeleteJobButtonProps) {
  const [isConfirmOpen, setIsConfirmOpen] = React.useState(false);
  const deleteMutation = useDeleteJob();

  const handleConfirmDelete = () => {
    deleteMutation.mutate(jobId, {
      onSettled: () => setIsConfirmOpen(false),
    });
  };

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        aria-label="작업 삭제"
        title="작업 삭제"
        data-testid="job-list-item-delete"
        onClick={() => setIsConfirmOpen(true)}
        className="text-muted-foreground hover:text-destructive"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-4 w-4"
          aria-hidden
        >
          <path d="M3 6h18" />
          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
          <path d="M10 11v6" />
          <path d="M14 11v6" />
        </svg>
      </Button>
      <Dialog open={isConfirmOpen} onOpenChange={setIsConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>이 작업을 영구 삭제할까요?</DialogTitle>
            <DialogDescription>
              {jobTitle} — 영상 파일, 자막, 번역 결과를 포함한 모든 산출물이 함께
              제거되며 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          {deleteMutation.isError && (
            <p
              role="alert"
              className="text-sm text-destructive"
              data-testid="job-list-item-delete-error"
            >
              삭제 실패: {(deleteMutation.error as Error).message}
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsConfirmOpen(false)}
              disabled={deleteMutation.isPending}
            >
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={handleConfirmDelete}
              disabled={deleteMutation.isPending}
              data-testid="job-list-item-delete-confirm"
            >
              {deleteMutation.isPending ? '삭제 중…' : '삭제'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
