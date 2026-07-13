import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../../api/client";
import type { PortfolioAnalytics } from "../../api/types";

export const portfolioAnalyticsKey = ["portfolio-analytics"] as const;

export function usePortfolioAnalytics() {
  return useQuery({
    queryKey: portfolioAnalyticsKey,
    queryFn: () => apiRequest<PortfolioAnalytics>("/api/analytics/portfolio"),
  });
}
