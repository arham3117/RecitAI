/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // The API is a separate process in development (§14). Proxying keeps the browser on
    // one origin, so there is no CORS surface and no API URL baked into the bundle.
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.RECITAI_API ?? "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};
export default nextConfig;
