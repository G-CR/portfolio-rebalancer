# 日报发送状态跨页面恢复实施计划

**Goal:** 站内切换页面后恢复手动日报发送的进度、成功或失败结果，发送期间避免重复提交。

**Architecture:** 复用应用已有的 React Query mutation cache。手动发送使用固定 mutation key，页面通过 `useMutationState` 读取最近一次发送状态，完成结果保留一小时。提交前检查共享缓存中的 pending 状态，沿用现有发送接口。

**Scope:** 站内路由切换；刷新或关闭浏览器后不恢复状态。不新增依赖、数据库表、队列或轮询接口。

## 实施与验证

- [x] 在 `frontend/tests/EmailSettingsForm.test.tsx` 添加发送期间离开并返回、离开期间成功和失败的用例，检查重复点击不会提交第二次请求；确认原实现失败。
- [x] 在 `frontend/src/features/settings/api.ts` 给手动发送设置 mutation key 和一小时缓存，通过 `useMutationState` 暴露共享状态，并在提交时拒绝重复 pending 请求。
- [x] 在 `frontend/src/features/settings/EmailSettingsForm.tsx` 使用有共享状态的提交方法，避免未处理的失败 Promise。
- [x] 运行邮件表单测试、前端全套测试和生产构建，检查 diff。210 个测试通过；TypeScript 的 19 项原有诊断没有增加。
- [x] 提交并推送代码，部署前端镜像；在公网页面用拦截的发送接口验证站内切页恢复，避免验收时发送实际邮件。公网浏览器已验证进行中状态、离开期间成功和失败、旧结果被新请求替换及重复提交保护，3 次验收请求全部被拦截。
