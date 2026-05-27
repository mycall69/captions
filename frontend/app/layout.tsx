import type { Metadata } from 'next';
import './globals.css';
import { AppHeader } from '@/components/header/AppHeader';
import { Providers } from './providers';

export const metadata: Metadata = {
  title: 'Bilingual Subtitle Studio',
  description: 'YouTube 영상을 한일 이중 자막으로 변환',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className="dark">
      <body>
        <Providers>
          <AppHeader />
          <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
