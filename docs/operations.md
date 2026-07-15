# 运维与恢复

## 服务与网络

`frontend` 是唯一发布端口的服务，Nginx 绑定 `127.0.0.1:${PORTFOLIO_PORT:-8080}` 并代理 `/api`。`api` 执行业务计算和迁移，`worker` 执行定时刷新与日终快照，`db` 保存 PostgreSQL 数据。API、worker 和数据库只存在于 Compose 内部网络。

使用 `docker compose config` 检查只有一个 `host_ip: 127.0.0.1`，且不存在发布的 5432 或 8000 端口。

## 数据卷

`postgres_data` 保存数据库。`secret_data` 保存加密供应商凭据所需的密钥。删除任一卷都会造成数据或密钥不可恢复；普通停机使用 `docker compose down`，不要使用 `down -v`。

## 刷新与旧值

worker 按设置中的 Asia/Shanghai 时间刷新必需行情。供应商优先级可以全局调整，每个持仓可单独覆盖。失败记录不会覆盖最近有效数值；页面会显示旧值、失败状态和来源。手动覆盖带有备注和可选失效时间。

API 镜像内置 AKShare，用于默认获取国内 ETF 行情。持仓页发现必需数据缺失时还会发起一次即时刷新。数据源全部失败时，数据库只保存数据源名称和 `provider_request_failed`、`provider_payload_invalid`、`provider_not_configured`、`provider_internal_error` 等安全类别，不保存请求 URL、密钥、原始响应或异常堆栈。外部网络不可用时应先重试，再按需要设置手动覆盖。

国际 ETF 与 USD/CNY 的默认顺序是 Yahoo Finance、新浪财经、Alpha Vantage。新浪财经不需要密钥，用于承接 Yahoo 的 HTTP 429、网络失败和无效载荷。Yahoo 返回值在入库前归一到 12 位小数，避免二进制浮点噪声超过 PostgreSQL `NUMERIC(28,12)`。记录的 `source` 始终是实际返回有效值的供应商。

## 凭据

Tushare 与 Alpha Vantage 密钥使用 Fernet 加密后写入数据库，密钥文件权限为 0600。日志只记录供应商、状态和异常类别。数据库备份不导出密钥卷，因此灾难恢复需要同时保留 `secret_data`。

## 备份

`make backup` 通过数据库容器执行 custom-format `pg_dump`，默认写入 `backups/`。输出文件权限为 0600，生成失败时不会留下看似完整的目标文件。

## 后端测试

运行 `make test-backend`。该目标使用独立的 Compose 项目和一次性 PostgreSQL 卷，测试结束后自动清理。不要直接对日常 Compose 数据库执行 `docker compose run --rm api uv run pytest`；迁移测试会修改结构并清空业务表。

## 恢复

`make restore FILE=...` 要求确认。脚本停止 API 和 worker，创建 `pre-restore` 安全备份，执行带 `--clean --if-exists` 的 `pg_restore`，然后恢复服务。失败时退出钩子也会尝试启动 API 和 worker。

恢复后运行：

```bash
docker compose ps
curl -fsS http://localhost:8080/api/health
docker compose logs --tail=100 api worker
```

## 故障处理

- API 不健康：检查迁移错误和数据库健康状态。
- 行情失败：查看数据源页，验证密钥或设置手动覆盖。
- 密钥无法解密：恢复与数据库匹配的 `secret_data`；仅恢复数据库不足以解密旧密文。
- 端口冲突：在 `.env` 修改 `PORTFOLIO_PORT` 后重新执行 `docker compose up -d`。
