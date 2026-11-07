<div align="center">

# Portfolio Rebalancer · 组合校准台

**管理持仓与成本，观察配置偏离，生成再平衡建议。**

面向个人投资组合的自托管应用，支持国内与美股资产、人民币与美元资金，以及行情刷新、历史快照和邮件日报。

[快速开始](#快速开始) · [功能概览](#功能概览) · [开发与测试](#开发与测试) · [备份与恢复](#备份与恢复) · [项目文档](#项目文档)

</div>

---

## 项目简介

组合校准台围绕目标配置管理投资组合：记录持仓、获取行情、计算市值和浮动盈亏，再根据可用资金与交易约束给出调整建议。

日常使用流程：

1. 设置资产类别及目标比例，录入持仓份额和平均成本。
2. 刷新行情，查看组合配置、盈亏和数据状态。
3. 输入本次可用资金，测算并参考建议交易清单。
4. 自行在券商下单，成交后更新实际持仓。

应用不连接券商下单。再平衡测算不会自动修改持仓，也不需要保存、开始或完成一个正式调仓流程。

## 功能概览

| 模块 | 主要功能 |
| --- | --- |
| 组合总览 | 核心资产池市值、参考成本、浮动盈亏、资产配置偏离及数据状态指示灯 |
| 资产配置 | 管理资产类别、目标比例与显示顺序，校验启用类别的目标合计为 100% |
| 持仓与成本 | 创建时直接录入份额与成本；支持追加买入、卖出调整、人工修正、替换标的及调整历史 |
| 盈亏分析 | 查看类别与持仓盈亏，切换人民币参考和交易币种口径 |
| 再平衡建议 | 根据人民币／美元现金、允许偏离、卖出与换汇约束生成建议；展示预计买入、卖出金额 |
| 历史快照 | 查看日终及手动快照，按时间、类型和资产类别筛选，追踪市值、成本和盈亏变化 |
| 数据源 | 配置行情供应商优先级、密钥、刷新时间以及手动价格和汇率 |
| 邮件日报 | 配置 SMTP、发送测试邮件、手动发送日报及定时发送组合摘要和再平衡建议 |
| 备份恢复 | 在页面导出、导入完整逻辑备份，或通过命令行进行 PostgreSQL 灾难恢复 |

支持的行情供应商包括 AKShare、Yahoo Finance、新浪财经、Tushare 和 Alpha Vantage。实际可用性取决于供应商接口、网络条件及凭据配置。

## 技术架构

| 层级 | 技术 |
| --- | --- |
| 前端 | React 19、TypeScript、Vite、TanStack Query、Recharts |
| API | Python 3.13、FastAPI、Pydantic、SQLAlchemy、Alembic |
| 后台任务 | APScheduler |
| 数据存储 | PostgreSQL 17 |
| 部署 | Docker Compose、Nginx |
| 测试 | pytest、Vitest、Testing Library、Playwright |

默认部署包含四个服务：

```text
浏览器 → frontend（Nginx :3000）→ api（FastAPI）→ db（PostgreSQL）
                                             ↑
                              worker（定时任务）→ db
```

`frontend` 提供静态页面并代理 `/api`。API 启动时执行数据库迁移，worker 负责定时刷新等任务。API 和数据库不直接发布宿主机端口。

## 快速开始

### 环境要求

- Git。
- Docker Desktop，或 Docker Engine 与 Docker Compose v2。
- 建议至少预留 4 GB 可用内存。
- 首次构建需要访问镜像仓库和依赖源，行情刷新需要访问对应供应商。

### 启动应用

```bash
git clone https://github.com/G-CR/portfolio-rebalancer.git
cd portfolio-rebalancer
cp .env.example .env
docker compose up -d --build
```

打开 [http://localhost:3000](http://localhost:3000)。首次构建和启动可能需要几分钟。

检查服务：

```bash
docker compose ps
curl -fsS http://localhost:3000/api/health
```

### 基础配置

`.env` 提供以下部署配置；供应商、邮件和再平衡参数在应用页面中设置。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `PORTFOLIO_PORT` | `3000` | 本地访问端口 |
| `POSTGRES_DB` | `portfolio` | 数据库名称 |
| `POSTGRES_USER` | `portfolio` | 数据库用户 |
| `POSTGRES_PASSWORD` | `portfolio` | 数据库密码 |
| `BACKUP_DIR` | `backups` | 命令行数据库备份目录 |

默认配置只监听 `127.0.0.1`，适合本机使用。仓库默认部署不提供应用层登录认证；部署到公网时，需要另行配置反向代理、HTTPS 和访问认证，并妥善管理部署凭据。

## 日常运行与升级

```bash
# 查看日志
docker compose logs -f api worker

# 停止服务，保留数据卷
docker compose down

# 升级前备份
make backup

# 拉取代码、构建并启动新版本
git pull --ff-only
docker compose build
docker compose up -d
```

不要在普通停机时使用 `docker compose down -v`，该参数会删除数据卷。

如果只想在本地查看页面，避免启动定时刷新和邮件任务，可使用：

```bash
docker compose stop worker
docker compose up -d db
docker compose build api frontend
docker compose up -d --no-deps api frontend
```

服务器部署请参阅[后端部署说明](docs/backend-deployment.md)。其中的脚本仅更新 API 与 worker 的 Python 代码，不适用于前端、依赖或数据库迁移变更。

## 开发与测试

### 前端

本机开发建议使用 Node.js 22，与前端 Docker 构建环境保持一致。

```bash
cd frontend
npm ci
npm run dev
```

当前 Vite 开发配置未设置 `/api` 代理。需要联调真实接口时，可使用 Docker Compose 提供的完整应用，或自行配置开发代理。

```bash
# 单元与组件测试
npm test

# 生产构建
npm run build
```

浏览器测试位于 `frontend/e2e`，通过 `npm run test:e2e` 执行；运行前需准备 Playwright 浏览器及其配置要求的应用服务，参见 [Playwright 配置](frontend/playwright.config.ts)。

### 后端

在仓库根目录使用隔离测试入口：

```bash
make test-backend

# 只运行指定用例
make test-backend PYTEST_ARGS='-q tests/unit/test_email_digest_render.py'
```

该入口使用独立 Compose 项目、一次性数据卷及专用数据库 `portfolio_test`，结束后清理测试资源。不要在日常运行的 Compose 项目中直接执行 pytest 或数据库集成测试，以免误用业务数据库。

## 备份与恢复

### 页面完整备份

在历史快照页的「完整备份与恢复」中，导出或导入 `.portfolio-backup` 文件。

- 恢复会替换当前逻辑数据，不会合并记录。
- 恢复前自动创建安全备份，保留最近五份成功的安全备份供下载或恢复。
- 逻辑备份包含业务历史，以及明文形式的供应商密钥和 SMTP 密码，应按敏感文件保管。
- 导出文件、已校验上传和一次性恢复令牌的有效期为 30 分钟。
- 支持的旧格式备份可导入同版或新版应用；新格式备份不能导入旧版应用。

### 数据库灾难恢复

当数据库损坏或 API 无法启动时，使用独立的 PostgreSQL 备份与恢复工具：

```bash
make backup
make restore FILE=backups/portfolio-<时间戳>.dump
```

数据库恢复需要确认，会停止 API 与 worker 写入，并先创建 `pre-restore` 安全备份。无人值守恢复可使用 `./scripts/restore.sh --yes FILE`。

| 数据卷 | 内容 |
| --- | --- |
| `postgres_data` | PostgreSQL 业务数据 |
| `secret_data` | 解密供应商和邮件凭据所需的密钥 |
| `backup_data` | 页面备份、上传及恢复相关文件 |

数据库 dump 不包含密钥卷。灾难恢复时需要同时保留与数据库匹配的 `secret_data`，否则旧凭据无法解密。

## 目录结构

```text
portfolio-rebalancer/
├── backend/
│   ├── app/              # API、业务服务、领域计算与后台任务
│   ├── alembic/          # 数据库迁移
│   └── tests/            # 后端单元与集成测试
├── frontend/
│   ├── src/              # 页面、功能组件、API 客户端与样式
│   ├── tests/            # 前端单元与组件测试
│   └── e2e/              # 浏览器端到端测试
├── docs/                 # 使用、运维、部署及设计文档
├── scripts/              # 备份、恢复与部署工具
├── compose.yaml          # 本地服务编排
├── .env.example          # 环境变量示例
└── Makefile              # 常用运行、测试与备份入口
```

## 项目文档

- [使用指南](docs/user-guide.md)
- [运维、数据源与故障恢复](docs/operations.md)
- [后端部署说明](docs/backend-deployment.md)
- [设计与实现记录](docs/superpowers/)

## 字体与资源

前端通过 Fontsource 随构建打包 Noto Sans SC 与 IBM Plex Mono，运行时不依赖外部字体 CDN。

- [Noto Sans SC](https://fonts.google.com/noto/specimen/Noto+Sans+SC)：SIL Open Font License 1.1。
- [IBM Plex Mono](https://github.com/IBM/plex)：SIL Open Font License 1.1。
