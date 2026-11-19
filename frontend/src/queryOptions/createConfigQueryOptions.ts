import { getAppConfig, getPhotoCredits } from "@/lib/config-api";
import { queryOptions } from "@tanstack/react-query";

export const createConfigQueryOptions = () => {
  return queryOptions({
    queryKey: ["app-config"],
    queryFn: getAppConfig,
    staleTime: 10 * 60 * 1000, // 10 minutes; flags only change on deploy
    retry: 1,
  });
};

export const createPhotoCreditsQueryOptions = () => {
  return queryOptions({
    queryKey: ["photo-credits"],
    queryFn: getPhotoCredits,
    staleTime: 60 * 60 * 1000, // credits only change on deploy
  });
};
