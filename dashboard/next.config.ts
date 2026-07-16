import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://backend:8000/api/:path*",
      },
      {
        source: "/health",
        destination: "http://backend:8000/health",
      },
      {
        source: "/ws",
        destination: "http://backend:8000/ws",
      },
    ];
  },
};

export default nextConfig;
