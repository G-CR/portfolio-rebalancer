import {
  BarChart3,
  Camera,
  ChartNoAxesCombined,
  Database,
  Gauge,
  Settings2,
  TableProperties,
  type LucideIcon,
} from "lucide-react";

export type AppRoute = {
  path: string;
  label: string;
  description: string;
  icon: LucideIcon;
};

export const APP_ROUTES: AppRoute[] = [
  { path: "/", label: "总览", description: "核对组合偏离、汇率影响与当前行动判断。", icon: Gauge },
  { path: "/allocation", label: "资产配置", description: "维护核心资产类别、目标比例与启用顺序。", icon: Settings2 },
  { path: "/holdings", label: "持仓与成本", description: "维护份额、成本价、成本汇率与调整记录。", icon: TableProperties },
  { path: "/analysis", label: "盈亏分析", description: "拆分价格影响、汇率影响与当前浮动盈亏。", icon: BarChart3 },
  { path: "/rebalance", label: "再平衡", description: "输入新增资金与约束，校准预计调整结果。", icon: ChartNoAxesCombined },
  { path: "/history", label: "历史快照", description: "复核日终、手动与再平衡事件的历史状态。", icon: Camera },
  { path: "/data-sources", label: "数据源", description: "检查行情、汇率来源、时间与有效状态。", icon: Database },
];
