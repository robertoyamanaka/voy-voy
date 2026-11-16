import type { NextConfig } from "next";

// The landing is fully static: `next build` writes plain files to out/, which
// Cloudflare serves as static assets. When the console needs a server, switch to
// the OpenNext Cloudflare adapter (@opennextjs/cloudflare) and drop `output`.
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
