/** @type {import('next').NextConfig} */
const nextConfig = {
  devIndicators: false,
  agentRules: false,
  allowedDevOrigins: ['127.0.0.1'],
  images: {
    unoptimized: true,
  },
}

export default nextConfig
