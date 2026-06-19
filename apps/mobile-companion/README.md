# Lightwork mobile companion (read-only)

Watch your Lightwork swarm from a phone: runs list, run detail with a live
event timeline, and an at-a-glance fleet summary — with an offline cache so
losing the network shows "as of 12 min ago" instead of a blank screen.

**Read-only by design.** The app only ever issues GET requests. It cannot
start, cancel, resume, approve, or answer anything — oversight actions stay
on the dashboard, where auth, same-origin checks, and rate limits live.

## Endpoints used (all existing dashboard routes)

From `packages/maverick-dashboard/maverick_dashboard/api.py`:

| Screen      | Endpoint |
|-------------|----------|
| Runs list   | `GET /api/v1/goals?limit=50` |
| Run detail  | `GET /api/v1/goals/{id}/events?since=0&limit=200` |
| Glance      | `GET /api/v1/oversight/active` + `GET /api/v1/spend` |
| Offline     | `GET /api/v1/offline/bundle` (optional; serves `maverick.offline_bundle.build_bundle`. Older dashboards without it still work — the offline cache just isn't refreshed) |

Updates are plain polling (5–15s per screen) — dependency-light and
battery-predictable; no SSE/websocket client to maintain.

## Running with Expo Go

This is a scaffold: `node_modules/` is not committed and no build artifacts
ship in the repo.

```bash
cd apps/mobile-companion
npm install            # or yarn / pnpm
npx expo start         # scan the QR code with the Expo Go app
```

Requirements:

- **Network**: the phone must reach the dashboard (`maverick dashboard`,
  default port 8400) — same Wi-Fi, VPN, or a tunnel. Set the base URL in the
  Settings tab (e.g. `http://192.168.1.20:8400`).
- **Token**: if dashboard auth is enabled, paste a bearer token in Settings.
  It is stored in the device keychain via `expo-secure-store`, never in
  plain storage. With auth off (local trusted networks only), leave it empty.
- **Offline cache**: the last good `/api/v1/offline/bundle` payload is kept
  in `AsyncStorage` (`@react-native-async-storage/async-storage`) and
  rendered with an "as of N min ago — offline" banner when fetches fail.

## Building store binaries

Producing installable iOS/Android binaries requires Expo's build tooling
(`eas build`) and platform credentials. That is not run in this repository —
the repo ships source only.

## Type checking

`npm run typecheck` (tsc) requires a local `npm install` first; the repo does
not vendor `node_modules`, so CI here only guarantees the sources are
syntactically valid TypeScript. Imports are limited to `react`,
`react-native`, `expo-status-bar`, `expo-secure-store`, and
`@react-native-async-storage/async-storage`.
