import type { NextConfig } from "next";

const API = process.env.RECLAIM_API ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // gzip would buffer the SSE agent stream (it only flushes on close). Local app, so compression isn't needed.
  compress: false,
  turbopack: {
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
  // Next is a thin client: all logic lives in the FastAPI backend, proxied same-origin (no CORS, SSE works).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
