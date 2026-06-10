/* Offline cache for the maverick-offline/1 bundle.
 *
 * The app saves the last successfully fetched bundle to AsyncStorage with a
 * timestamp; when the dashboard is unreachable, screens render the cached
 * bundle behind an "as of N min ago — offline" banner instead of a blank
 * error. The bundle is built server-side by maverick.offline_bundle (bounded,
 * versioned, no secrets), so caching it on-device is safe by construction.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

import type { OfflineBundle } from "./api";

const CACHE_KEY = "maverick.offlineBundle.v1";
const SCHEMA = "maverick-offline/1";

export type CachedBundle = { savedAt: number; bundle: OfflineBundle };

export async function saveBundle(bundle: OfflineBundle): Promise<void> {
  if (bundle.schema !== SCHEMA) return; // refuse shapes we don't understand
  const entry: CachedBundle = { savedAt: Date.now(), bundle };
  await AsyncStorage.setItem(CACHE_KEY, JSON.stringify(entry));
}

export async function loadBundle(): Promise<CachedBundle | null> {
  try {
    const raw = await AsyncStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const entry = JSON.parse(raw) as CachedBundle;
    if (!entry?.bundle || entry.bundle.schema !== SCHEMA) return null;
    return entry;
  } catch {
    return null; // corrupt cache reads as "no cache"
  }
}

export function ageMinutes(entry: CachedBundle, now: number = Date.now()): number {
  return Math.max(0, Math.round((now - entry.savedAt) / 60000));
}

export function offlineBanner(entry: CachedBundle): string {
  return `as of ${ageMinutes(entry)} min ago — offline`;
}
