'use client';
import { forwardRef } from 'react';

interface VideoPlayerProps {
  jobId: string;
  onTimeUpdate?: (currentTimeMs: number) => void;
}

export const VideoPlayer = forwardRef<HTMLVideoElement, VideoPlayerProps>(
  function VideoPlayer({ jobId, onTimeUpdate }, ref) {
    return (
      <video
        ref={ref}
        controls
        className="w-full rounded-lg bg-black"
        src={`/api/v1/jobs/${jobId}/video`}
        onTimeUpdate={(e) => onTimeUpdate?.(e.currentTarget.currentTime * 1000)}
      />
    );
  },
);
