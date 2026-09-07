/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output is for the Docker image only. `next start` cannot serve a
  // standalone build's client chunks, which leaves the browser with server HTML
  // that hydration then wipes — the page looks empty. The Dockerfile sets
  // NEXT_OUTPUT=standalone and runs `node .next/standalone/server.js`.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // Trace from this directory, not the monorepo root. node_modules lives here
  // in both layouts, so the standalone output lands at the same path locally
  // (apps/frontend/.next/standalone/server.js) and in the image — the Dockerfile's
  // CMD depends on that being stable. Tracing from ../../ silently moved
  // server.js to standalone/app/server.js inside the container.
  outputFileTracingRoot: import.meta.dirname,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
