/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // Allow importing JSON files from outside the app dir.
    externalDir: true,
  },
};

export default nextConfig;
