import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import flowbiteReact from 'flowbite-react/plugin/vite';
import viteTsconfigPaths from 'vite-tsconfig-paths';
import path from 'path';

const BACKEND_PROXY_ROUTES = [
    '/api',
    '/auth',
    '/webhook',
    '/media-sources',
    '/health',
    '/ws',
    '/media',
    '/agents-sdk',
];

function buildBackendProxy(target: string) {
    return Object.fromEntries(
        BACKEND_PROXY_ROUTES.map((route) => [
            route,
            {
                target,
                changeOrigin: true,
                ws: route === '/ws' || route === '/api',
            },
        ])
    );
}

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '');
    const devProxyTarget = env.VITE_DEV_PROXY_TARGET || process.env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8002';
    const devHost = env.VITE_DEV_HOST || process.env.VITE_DEV_HOST || '0.0.0.0';
    const devPort = Number(env.VITE_DEV_PORT || process.env.VITE_DEV_PORT || 3004);

    return {
        plugins: [react(), flowbiteReact(), tailwindcss(), viteTsconfigPaths()],
        resolve: {
            alias: {
                '@': path.resolve(__dirname, './src'),
            },
        },
        server: {
            host: devHost,
            port: devPort,
            strictPort: true,
            proxy: buildBackendProxy(devProxyTarget),
        },
        build: {
            outDir: 'build',
        },
    };
});
