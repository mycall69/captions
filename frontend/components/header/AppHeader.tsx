import Link from 'next/link';
import { Button } from '@/components/ui/button';

export function AppHeader() {
  return (
    <header className="border-b border-border bg-background">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
        {/* 좌측: 로고 + 제품명 — 클릭 시 홈(/)으로 이동 */}
        <Link href="/" className="flex items-center gap-2 text-base font-semibold">
          <span aria-hidden>◇</span>
          <span>Bilingual Subtitle Studio</span>
        </Link>

        {/* 우측: 내비게이션 */}
        <nav className="flex items-center gap-2">
          <Button asChild variant="ghost">
            <Link href="/">새 작업</Link>
          </Button>
          {/* 최근 작업 드롭다운은 US3 (T119)에서 추가 예정 */}
        </nav>
      </div>
    </header>
  );
}
