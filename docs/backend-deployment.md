# 后端代码部署说明

`scripts/deploy_backend.py` 用于把已经提交到 Git 的 `backend/app` Python 代码部署到现有的 Docker Compose 服务器。它只更新 API 和 worker 镜像；PostgreSQL 容器、数据卷、服务器上的 `.env`、前端镜像和已有凭据不会被替换。

脚本以服务器当前运行的 API 镜像为基础构建新镜像。部署前，它会比较本地与当前镜像中的 `pyproject.toml`、`uv.lock`、`alembic.ini` 和 Alembic 迁移文件。依赖或数据库迁移发生变化时，脚本会停止。这类变更以及前端变更需要另行执行完整部署。

## 在 Windows PowerShell 中运行

先在本机安装 Paramiko，并提交准备部署的代码。然后在 PowerShell 中输入连接信息：

```powershell
python -m pip install paramiko
$env:DEPLOY_HOST = Read-Host '服务器 SSH 地址'
$env:DEPLOY_USER = Read-Host 'SSH 用户名'
$env:DEPLOY_SSH_PORT = Read-Host 'SSH 端口'
$env:DEPLOY_REMOTE_DIR = Read-Host '服务器上的 Compose 项目目录'
$env:DEPLOY_HOST_KEY_SHA256 = Read-Host '已核实的 SSH 主机密钥 SHA256 指纹'
python scripts/deploy_backend.py
```

这些值只保存在当前 PowerShell 会话中，输入命令不会把实际值写进仓库或命令历史。脚本会隐藏输入 SSH 密码，也不会保存密码。若使用密钥登录，可以在运行脚本时加 `--identity-file PATH` 或 `--use-agent`。

运行前，请从可信渠道核实服务器的 SSH 主机密钥指纹。指纹不匹配时，脚本会拒绝连接。

运行结束后，清除当前会话中的连接信息：

```powershell
Remove-Item Env:DEPLOY_HOST,Env:DEPLOY_USER,Env:DEPLOY_SSH_PORT,Env:DEPLOY_REMOTE_DIR,Env:DEPLOY_HOST_KEY_SHA256
```

## 脚本会执行什么

脚本要求 Git 工作区没有未提交的改动。它只打包 `backend/app` 下的 `.py` 文件，在服务器上构建带版本标签的新镜像，并先检查新镜像能否导入应用。随后它备份生产 Compose 覆盖文件，只重建 API 和 worker，等待 API 健康检查通过。若启动失败，脚本会恢复原来的 Compose 配置和镜像。备份的 Compose 文件会留在服务器上，方便检查。

部署脚本不会主动刷新行情或发送邮件。本仓库不保存服务器地址、端口、用户名、密码、主机指纹或服务器目录。如果需要在本机记录这些信息，可使用 `.deploy.local.*` 文件名；该模式已加入 `.gitignore`，但仍应妥善保管该文件。
