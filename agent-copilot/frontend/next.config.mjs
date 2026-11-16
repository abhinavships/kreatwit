/** @type {import('next').NextConfig} */
// Static export: the backend serves frontend/out from the same origin as the API (see ../Dockerfile).
const nextConfig = { reactStrictMode: true, output: "export", trailingSlash: true };
export default nextConfig;
