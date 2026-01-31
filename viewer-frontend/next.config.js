/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config) => {
    config.resolve.alias.canvas = false;
    return config;
  },
  async rewrites() {
    return [
      {
        source: '/api/pipeline/:path*',
        destination: 'http://localhost:8001/api/:path*',
      },
    ];
  },
}

module.exports = nextConfig
