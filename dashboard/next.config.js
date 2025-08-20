/** @type {import('next').NextConfig} */

const nextConfig = {
  // Enable React strict mode for development best practices
  reactStrictMode: true,

  // Customize image optimization
  images: {
    domains: [], // Add any external image domains here
    formats: ['image/avif', 'image/webp'],
    deviceSizes: [640, 750, 828, 1080, 1200, 1920, 2048],
    imageSizes: [16, 32, 48, 64, 96, 128, 256],
  },

  // TypeScript configuration
  typescript: {
    // Dangerously allow production builds to successfully complete even if
    // your project has type errors.
    // !! Consider setting this to true in production
    ignoreBuildErrors: false,
  },

  // Build configuration
  swcMinify: true, // Use SWC for minification (faster than Terser)
  
  // Compiler options
  compiler: {
    // Remove console.log in production
    removeConsole: process.env.NODE_ENV === 'production',
  },

  // Enable experimental features if needed
  experimental: {
    // Enable server actions
    serverActions: true,
    // Optimize fonts
    optimizeFonts: true,
    // Enable modern webpack optimizations
    modern: true,
  },

  // Configure redirects if needed
  async redirects() {
    return []
  },

  // Configure headers if needed
  async headers() {
    return []
  },
}

module.exports = nextConfig