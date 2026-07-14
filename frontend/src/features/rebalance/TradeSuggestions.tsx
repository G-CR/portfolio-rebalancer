import type { RebalanceTradeSuggestion } from "../../api/types";
import { formatAmount, formatDecimal } from "../analytics/format";
import styles from "./Rebalance.module.css";

export function TradeSuggestions({ trades }: { trades: RebalanceTradeSuggestion[] }) {
  return (
    <section className={styles.trades} aria-labelledby="trade-suggestions-title">
      <header className={styles.sectionHeading}><div><p>TRADE LIST</p><h2 id="trade-suggestions-title">建议交易清单</h2></div><span>参考金额不代表实际成交</span></header>
      {trades.length === 0 ? <p className={styles.empty}>当前口径下不需要产生交易。</p> : <div className={styles.tableWrap}><table>
        <thead><tr><th>标的</th><th>动作</th><th>建议份额</th><th>交易币种金额</th><th>人民币参考</th><th>原因</th></tr></thead>
        <tbody>{trades.map((trade, index) => <tr key={`${trade.symbol}-${trade.action}-${index}`} aria-label={`${trade.symbol} ${trade.action === "buy" ? "买入" : "卖出"}`}>
          <th scope="row">{trade.symbol}</th>
          <td><strong className={trade.action === "buy" ? styles.buy : styles.sell}>{trade.action === "buy" ? "买入" : "卖出"}</strong></td>
          <td>{formatDecimal(trade.quantity, 6)}</td><td>{formatAmount(trade.amount_trade_currency, 2)}</td><td>{formatAmount(trade.amount_cny, 0)}</td><td>{trade.reason}</td>
        </tr>)}</tbody>
      </table></div>}
    </section>
  );
}
