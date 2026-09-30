# 再平衡测算跨页面恢复实施计划

> **For agentic workers:** Use TDD for each behavior. Work inline in this session; no delegation is requested.

**Goal:** 返回再平衡页面后恢复后台测算进度与最近成功结果，并安全处理过期输入。

**Architecture:** 数据库任务是唯一恢复来源。后端提供最新任务查询及输入签名校验；前端从任务恢复状态并沿用现有按 ID 轮询；正式方案保存进行签名乐观校验。

**Tech Stack:** FastAPI、SQLAlchemy、PostgreSQL、React、TanStack Query、Vitest。

## 任务 1：后端任务恢复接口

- [ ] 在 `backend/tests/integration/test_rebalance_api.py` 添加无任务、最新任务排序、进行中、成功和失败查询用例，先确认接口不存在。
- [ ] 在 `backend/app/services/rebalance_preview_jobs.py` 与 `backend/app/api/routes/rebalance.py` 增加最新任务查询；响应包含输入快照和时间。
- [ ] 运行针对性集成测试。

## 任务 2：结果有效性与保存保护

- [ ] 先测试行情值、持仓版本或目标变化后，成功结果变为历史结果；原输入不变时仍可使用。
- [ ] 在 `backend/app/services/rebalance_version.py` 增加稳定的测算输入签名，并在 `backend/app/services/rebalancing.py` 的预览结果中保存签名。
- [ ] 给正式方案保存请求增加可选的预期签名；不匹配时返回冲突并避免写入方案。
- [ ] 运行后端相关单元与集成测试。

## 任务 3：前端跨页面恢复

- [ ] 在 `frontend/tests/RebalancePage.test.tsx` 添加切换页面后仍显示运行中、完成后直接显示结果、重新进入后回显上次结果、数据变化后禁用正式操作的失败测试。
- [ ] 在 `frontend/src/features/rebalance/api.ts` 加最新任务查询；`frontend/src/pages/RebalancePage.tsx` 恢复任务 ID、结果、错误与表单输入。
- [ ] 保存正式方案时传入签名；成功后展示实际保存的方案结果。
- [ ] 运行前端定向与全量测试、生产构建。

## 任务 4：部署与验收

- [ ] 核对代码与数据库无迁移变更，提交并推送已验证代码。
- [ ] 部署 API、worker 和前端，保留数据库及密钥卷。
- [ ] 在公网入口验证最新任务接口、页面跨路由继续、完成结果恢复、健康检查及容器日志。
