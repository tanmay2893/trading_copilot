import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Do NOT set allowedDevOrigins here for ngrok: defining it switches Next dev to strict
  // "block" mode, which 403s /_next/* when Sec-Fetch-Site is cross-site — that happens when
  // the document is on *.ngrok-free.app but dev chunks load from localhost:3070 (broken CSS/JS).
  async rewrites() {
    // In development, proxy /api to the backend so one URL (no separate proxy needed)
    if (process.env.NODE_ENV === "development") {
      return [
        { source: "/api/:path*", destination: "http://localhost:6700/api/:path*" },
      ];
    }
    return [];
  },
};

export default nextConfig;
