import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../../api/client";
import { portfolioAnalyticsKey } from "../../api/queryKeys";
import type { PortfolioAnalytics } from "../../api/types";

export { portfolioAnalyticsKey } from "../../api/queryKeys";

export function usePortfolioAnalytics() {
  return useQuery({
    queryKey: portfolioAnalyticsKey,
    queryFn: () => apiRequest<PortfolioAnalytics>("/api/analytics/portfolio"),
  });
}
