/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  async redirects() {
    return [
      { source: '/dashboard', destination: '/console', permanent: false },
      { source: '/forensics', destination: '/console', permanent: false },
    ]
  },
}

export default nextConfig
