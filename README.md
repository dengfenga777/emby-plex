# MoviePilot Request System

一个面向 Telegram Bot + Telegram MiniApp 的求片系统 MVP。

当前仓库已经包含一条可运行的最小闭环：

- `backend/`
  - FastAPI API
  - SQLite 数据存储
  - Telegram WebApp / 开发模式登录
  - 请求状态流转
  - 管理员审批接口
  - MoviePilot mock 适配层
  - Telegram Bot 基础命令骨架
- `miniapp/`
  - React + Vite MiniApp
  - 搜索、提交求片、我的请求、请求详情
  - 管理员待审批队列

## 当前假设

- 默认使用 `MOVIEPILOT_MODE=mock`
- 已按官方 `MoviePilot` `v2` 的 `/api/v1` 接口接入搜索、查库、查订阅、创建订阅和基础状态轮询
- 开发环境允许通过 `/api/auth/telegram` 的 `profile` 参数直接登录
- `DEFAULT_ADMIN_IDS` 里的 Telegram 用户 ID 会被自动识别为管理员

## 已接入的 MoviePilot 官方接口

当前后端适配层对接的是这组接口：

- `POST /api/v1/login/access-token`
- `GET /api/v1/media/search`
- `GET /api/v1/mediaserver/exists`
- `GET /api/v1/subscribe/media/{mediaid}`
- `POST /api/v1/subscribe/`
- `GET /api/v1/download/`
- `GET /api/v1/transfer/queue`

推荐配置方式：

- 优先填 `MOVIEPILOT_API_KEY`
- 如果没有 API Token，再填 `MOVIEPILOT_USERNAME` / `MOVIEPILOT_PASSWORD`

## 本地启动

### 1. 启动后端

```bash
cd /Users/cc/Documents/Playground/backend
cp .env.example .env
uv sync --extra dev
uv run uvicorn app.main:app --reload
```

后端默认地址：

- `http://127.0.0.1:8000`
- OpenAPI: `http://127.0.0.1:8000/docs`

### 2. 启动 MiniApp

```bash
cd /Users/cc/Documents/Playground/miniapp
cp .env.example .env
npm install
npm run dev
```

前端默认地址：

- `http://127.0.0.1:5173`

### 3. 启动 Telegram Bot

配置 `backend/.env` 中的 `TELEGRAM_BOT_TOKEN` 后：

```bash
cd /Users/cc/Documents/Playground/backend
uv run python -m app.bot
```

## 已完成的接口

- `POST /api/auth/telegram`
- `GET /api/auth/me`
- `GET /api/health`
- `GET /api/search`
- `POST /api/requests`
- `GET /api/my/requests`
- `GET /api/requests/{id}`
- `GET /api/admin/requests?status=pending`
- `POST /api/admin/requests/{id}/approve`
- `POST /api/admin/requests/{id}/reject`

## 质量检查

已完成以下验证：

- `uv run pytest`
- `uv run ruff check`
- `npm run build`
- 本地启动后端并验证 `/api/health`、`/api/auth/telegram`

## 下一步建议

最值得继续往下做的是这几块：

1. 接上你自己的 MoviePilot 实例，验证真实搜索结果、查库命中和创建订阅链路。
2. 给 Telegram Bot 补齐搜索按钮、审批通知和状态推送。
3. 增加重复求片合并、黑名单、每日额度限制。
4. 把 SQLite 迁移到 PostgreSQL，并补 Alembic 迁移。
