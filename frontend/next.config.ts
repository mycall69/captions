import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // API 서버 프록시 (개발 환경)
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: 'http://localhost:8000/v1/:path*',
      },
    ];
  },
};

export default nextConfig;
