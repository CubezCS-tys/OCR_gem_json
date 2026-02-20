const BACKEND = process.env.BACKEND_URL || 'http://localhost:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      { source: '/api/:path*',  destination: `${BACKEND}/api/:path*` },
      { source: '/auth/:path*', destination: `${BACKEND}/auth/:path*` },
    ];
  },
};

export default nextConfig;
