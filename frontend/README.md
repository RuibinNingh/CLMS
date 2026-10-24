# 作文档案馆前端

React / TypeScript / Vite。所有业务使用同源 `/api`，无演示数据或模型调用。生产后端直接提供 `dist/`。

```bash
cd frontend
npm ci
npm run typecheck
npm test
npm run build
```

本地开发时，在仓库根目录使用已安装后端依赖的环境启动 API：

```bash
CLMS_PUBLIC_ORIGIN=http://127.0.0.1:5173 python3 -m backend.app.cli serve --port 8000
```

另一终端执行 `cd frontend && npm run dev`，打开 `http://127.0.0.1:5173`。Vite 将 API 代理到 8000；同源检查使用浏览器实际地址。首次设置令牌位于服务端配置的数据目录，按根 README 初始化。

路由采用 hash：`#/archive`、`#/prompt/{id}?version={id}`、`#/submit`、`#/reviews?id={id}`、`#/categories`、`#/settings`。评价回执指定准确版本，历史稿件不会被“最新稿”替换。

审核、反思、人工评价、题目修改及上传草稿写入本浏览器 localStorage，输入时立即保留。审核草稿绑定服务端 revision，冲突不会覆盖本地修订；通过要求已保存修订和当前 digest。凭据不写入 localStorage。

主题和平台样式集中在 `src/app/`。输入保持 16px；hover 按输入能力启用；动态视口和安全区保护手机控件。Playwright 响应式模拟与实体手机验证分别记录，模拟不代表硬件验证。

单测在 `tests/unit/`，真实浏览器测试在 `tests/browser/`；统一完整验证使用仓库根 `python3 scripts/verify.py --all --report artifacts/verification.json`。
