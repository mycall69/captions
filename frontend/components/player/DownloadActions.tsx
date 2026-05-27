'use client';
import { Button } from '@/components/ui/button';
import { usePlayerPreferences } from '@/lib/stores/playerStore';

export function DownloadActions({ jobId }: { jobId: string }) {
  const { order } = usePlayerPreferences();

  function downloadLink(format: 'srt' | 'vtt'): string {
    return `/api/v1/jobs/${jobId}/download?format=${format}&order=${order}`;
  }

  return (
    <div className="flex gap-2">
      <Button asChild variant="outline">
        <a href={downloadLink('srt')} download>SRT 다운로드</a>
      </Button>
      <Button asChild variant="outline">
        <a href={downloadLink('vtt')} download>VTT 다운로드</a>
      </Button>
    </div>
  );
}
