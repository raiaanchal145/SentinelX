import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev sharing (`npm run dev:share`, see README "Sharing the dev
// environment"): SENTINELX_SHARE=1 is set by the launcher for that one
// run only. It does three things plain `npm run dev` never does:
//   - host: true          -- listen on all interfaces so http://<lan-ip>:5173
//                            works from a phone on the same Wi-Fi;
//   - allowedHosts: true  -- Vite >=6 blocks unknown Host headers, which
//                            every tunnel domain would be; allow them here;
//   - proxy /api -> 8000  -- the phone talks to ONE origin and Vite
//                            forwards API calls to the loopback backend,
//                            so the backend never has to be LAN-exposed.
// Without SENTINELX_SHARE=1 the config is exactly what it always was.
const SHARE = process.env.SENTINELX_SHARE === '1'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  ...(SHARE
    ? {
        server: {
          host: true,
          allowedHosts: true,
          proxy: {
            '/api': {
              target: 'http://localhost:8000',
              changeOrigin: true,
            },
          },
        },
      }
    : {}),
})