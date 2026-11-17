"use client";

import { useQuery } from "@tanstack/react-query";
import { createConfigQueryOptions } from "@/queryOptions/createConfigQueryOptions";
import { DEFAULT_APP_CONFIG } from "@/lib/config-api";
import { AppConfig } from "@/types/config";

/**
 * Runtime feature flags and demo-mode info from the backend.
 *
 * Falls back to `DEFAULT_APP_CONFIG` (demo off, AI shown) while loading or if the
 * request fails, so an older backend without `/config` behaves exactly as before.
 */
export function useAppConfig(): AppConfig & { isDemo: boolean } {
  const { data } = useQuery(createConfigQueryOptions());
  const config = data ?? DEFAULT_APP_CONFIG;
  return { ...config, isDemo: config.demo.enabled };
}
