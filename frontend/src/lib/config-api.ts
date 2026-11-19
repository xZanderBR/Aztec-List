import { API_BASE_URL } from "@/lib/constants";
import { AppConfig } from "@/types/config";

/**
 * Fallback used until `/config` loads, or when the backend predates it: no demo mode,
 * and every AI feature shown (the app's behavior before the config endpoint existed).
 */
export const DEFAULT_APP_CONFIG: AppConfig = {
  demo: { enabled: false, next_reset_at: null, personas: [] },
  ai: { semantic_search: true, assistant: true, generate_description: true },
};

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * Fetch the public runtime config (demo mode, personas, AI feature flags).
 *
 * Rejects responses without the expected shape, and fills any missing field from
 * `DEFAULT_APP_CONFIG`, so a proxy error page or a partial response can't break the UI.
 */
export const getAppConfig = async (): Promise<AppConfig> => {
  const res = await fetch(`${API_BASE_URL}/config`);
  if (!res.ok) {
    throw new Error(`Failed to load app config: ${res.status}`);
  }
  const data: unknown = await res.json();
  if (!isObject(data) || !isObject(data.demo) || !isObject(data.ai)) {
    throw new Error("Unexpected app config response");
  }
  const demo = { ...DEFAULT_APP_CONFIG.demo, ...data.demo } as AppConfig["demo"];
  return {
    demo: { ...demo, personas: Array.isArray(demo.personas) ? demo.personas : [] },
    ai: { ...DEFAULT_APP_CONFIG.ai, ...data.ai } as AppConfig["ai"],
  };
};
