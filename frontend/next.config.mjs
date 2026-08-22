/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Railway builds the web service from this directory; standalone output keeps the
  // deployed image small and lets `next start` run without the full node_modules tree.
  output: "standalone",
  poweredByHeader: false,
};

export default nextConfig;
