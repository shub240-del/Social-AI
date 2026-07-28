/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Never ship a build that only "works" because errors were ignored.
  eslint: { ignoreDuringBuilds: false },
  typescript: { ignoreBuildErrors: false },
  poweredByHeader: false,
  output: 'standalone',
};
export default nextConfig;
