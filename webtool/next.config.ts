import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allows building into a separate folder (NEXT_DIST_DIR=.next-check) without clobbering a running `next dev`.
  devIndicators: false, // hide the Next.js "N" badge in dev
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
