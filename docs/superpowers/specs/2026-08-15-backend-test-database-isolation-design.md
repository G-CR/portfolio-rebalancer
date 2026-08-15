# 后端测试数据库隔离设计

## 背景

仓库已有 `make test-backend`，它通过 `COMPOSE_PROJECT_NAME=portfolio-rebalancer-test` 使用独立 Compose 项目和独立 Docker 卷。但 pytest 自身仍默认连接 `postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio`，而数据库重置夹具会在每个测试前后对业务表执行 `TRUNCATE ... CASCADE`。因此，只要绕过 Makefile 直接在主 Compose 项目的 API 容器中运行 pytest，就会清空真实数据。

## 目标

- 后端测试只能清理名称明确为测试用途的数据库。
- `make test-backend` 继续提供一条跨平台一致的标准入口，并使用独立 Compose 项目、独立数据库和独立卷。
- 任何旧的或误用的原始 pytest 命令在执行首个 `TRUNCATE` 前失败，且错误信息说明正确命令。
- 生产数据库、生产卷、密钥卷和正常服务启动方式不受影响。

## 隔离架构

采用三层防护：

1. **Compose 项目隔离**：`make test-backend` 保持 `COMPOSE_PROJECT_NAME=portfolio-rebalancer-test`，测试容器和卷不会与 `portfolio-rebalancer` 主项目重名。
2. **数据库身份隔离**：测试 PostgreSQL 使用数据库名 `portfolio_test`；测试 API 的 `DATABASE_URL` 显式指向 `db:5432/portfolio_test`，不再依赖 pytest 中的生产同名默认值。
3. **pytest 清库熔断**：任何清表操作前，安全检查必须同时确认：
   - `DATABASE_URL` 已显式设置；
   - URL 中数据库名严格等于 `portfolio_test`；
   - `PYTEST_DATABASE_RESET_TOKEN` 严格等于 `portfolio_test`。

任一条件不满足时抛出明确异常，不创建测试会话、不运行迁移、不执行 `TRUNCATE`。确认标记不是独立安全边界，而是防止仅凭错误数据库名称或继承环境变量意外授权清库的第二道代码级检查。

## 标准测试入口

`make test-backend` 在当前单个 shell 作用域内设置：

```text
COMPOSE_PROJECT_NAME=portfolio-rebalancer-test
POSTGRES_DB=portfolio_test
DATABASE_URL=postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio_test
PYTEST_DATABASE_RESET_TOKEN=portfolio_test
PORTFOLIO_PORT=0
```

测试入口继续执行以下顺序：

1. 仅清理同名测试 Compose 项目及其测试卷；
2. 启动测试数据库；
3. 构建测试 API 镜像；
4. 对 `portfolio_test` 执行迁移；
5. 对 `portfolio_test` 运行 pytest；
6. 无论成功或失败，清理测试项目及测试卷。

传递给容器的 `DATABASE_URL` 和重置标记必须通过 `docker compose run -e ...` 显式注入，不能假定宿主机导出的普通环境变量会自动进入容器。

## pytest 安全边界

数据库 URL 校验提取为无副作用的小函数，便于直接单元测试。`conftest.py` 在创建测试引擎之前调用它，并将已验证 URL 传给 SQLAlchemy。

错误信息必须包含：

- 被拒绝的数据库名称或“未设置”；
- 说明业务数据库绝不允许被测试重置；
- 正确入口 `make test-backend`。

安全检查不得提供 `--force`、通配数据库名或生产库豁免开关。

## 文档与操作约束

- README 和运维文档把 `make test-backend` 作为唯一支持的后端测试命令。
- 明确禁止在主项目中运行 `docker compose run api pytest` 或直接执行数据库集成测试。
- 保留现有“不要对主项目执行 `docker compose down -v`”警告。
- 不在本次改动中自动创建生产备份；备份仍由现有 `make backup` 独立负责。

## 测试策略

### 安全检查单元测试

- 未设置 `DATABASE_URL` 时拒绝。
- 数据库名为 `portfolio` 时拒绝，即使重置标记存在。
- 数据库名为 `portfolio_test` 但重置标记缺失或错误时拒绝。
- 数据库名和重置标记都严格为 `portfolio_test` 时允许。
- 带查询参数的合法测试 URL 仍能正确识别数据库名。

### 集成验证

- 使用 `make test-backend` 运行测试，确认迁移和测试均连接 `portfolio_test`。
- 在主 API 容器中尝试旧命令时，确认 pytest 在清表前失败，并且主数据库的哨兵数据保持不变。
- 测试结束后确认主 Compose 项目仍在运行，`portfolio-rebalancer_postgres_data` 未被删除或替换。

## 验收标准

1. 标准入口仅操作 `portfolio-rebalancer-test` 项目的 `portfolio_test` 数据库。
2. 原始 pytest 误用路径无法通过代码级清库检查。
3. 失败发生在任何业务表清理之前。
4. 主数据库哨兵数据在隔离验证前后完全一致。
5. 文档不再给出可能连接真实库的后端测试命令。

## 非目标

- 不恢复已丢失的数据。
- 不修改生产数据库架构或业务 API。
- 不引入远程数据库、CI 服务或新的密钥系统。
- 不用自动备份代替测试隔离。
