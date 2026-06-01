/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@ai-voice/shared", "@ai-voice/db"],
};
export default nextConfig;
