import { getAppConfig } from "@/lib/config-api";
import { queryOptions } from "@tanstack/react-query";

export const createConfigQueryOptions = () => {
  return queryOptions({
    queryKey: ["app-config"],
    queryFn: getAppConfig,
    staleTime: 10 * 60 * 1000, // 10 minutes; flags only change on deploy
    retry: 1,
  });
};
