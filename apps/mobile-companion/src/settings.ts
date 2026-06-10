/* Dashboard connection settings, stored in the device keychain via
 * expo-secure-store (the token never touches AsyncStorage or logs). */
import * as SecureStore from "expo-secure-store";

import type { Settings } from "./api";

const BASE_URL_KEY = "maverick.baseUrl";
const TOKEN_KEY = "maverick.token";

export const DEFAULT_BASE_URL = "http://127.0.0.1:8400";

export async function loadSettings(): Promise<Settings> {
  const baseUrl = (await SecureStore.getItemAsync(BASE_URL_KEY)) ?? DEFAULT_BASE_URL;
  const token = (await SecureStore.getItemAsync(TOKEN_KEY)) ?? "";
  return { baseUrl, token };
}

export async function saveSettings(s: Settings): Promise<void> {
  await SecureStore.setItemAsync(BASE_URL_KEY, s.baseUrl.trim());
  await SecureStore.setItemAsync(TOKEN_KEY, s.token.trim());
}
