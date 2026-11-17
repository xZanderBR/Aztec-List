import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
  output: "standalone", // Required for Docker deployment
  // Pin the project root to frontend/. Otherwise Next infers it from lockfiles, finds the
  // placeholder package-lock.json at the repo root, and warns on every build.
  turbopack: {
    root: path.join(__dirname),
  },
  images: {
    unoptimized: true, // Served as-is from the API host (NEXT_PUBLIC_STATIC_BASE_URL)
  },
};

export default nextConfig;
