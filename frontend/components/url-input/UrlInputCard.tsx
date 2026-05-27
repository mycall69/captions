'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';

const YOUTUBE_HOSTS = new Set(['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be']);

function isValidYouTubeUrl(value: string): boolean {
  try {
    const u = new URL(value);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
    return YOUTUBE_HOSTS.has(u.hostname.toLowerCase());
  } catch {
    return false;
  }
}

interface UrlInputCardProps {
  onSubmit?: (url: string) => void;
}

export function UrlInputCard({ onSubmit }: UrlInputCardProps) {
  const [url, setUrl] = useState('');
  const [touched, setTouched] = useState(false);
  const valid = url.trim() !== '' && isValidYouTubeUrl(url.trim());
  const showError = touched && url.trim() !== '' && !valid;

  return (
    <Card className="mb-6">
      <CardContent className="space-y-3 p-6">
        <div className="flex gap-2">
          <Input
            placeholder="https://www.youtube.com/watch?v=..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onBlur={() => setTouched(true)}
            aria-invalid={showError}
            aria-describedby={showError ? 'url-error' : undefined}
          />
          <Button
            type="button"
            disabled={!valid}
            onClick={() => valid && onSubmit?.(url.trim())}
          >
            시작
          </Button>
        </div>
        {showError && (
          <p id="url-error" role="alert" className="text-sm text-destructive">
            유효한 YouTube 영상 URL을 입력해 주세요.
          </p>
        )}
        <p className="text-sm text-muted-foreground">
          유효한 YouTube 단일 영상 URL을 붙여넣으세요
        </p>
      </CardContent>
    </Card>
  );
}
