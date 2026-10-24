import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { join } from "node:path";

const evidence = process.env.CLMS_TEST_EVIDENCE!;
const password = process.env.CLMS_TEST_PASSWORD!;
let promptId = "",
  versionId = "",
  reviewId = "";
const login = async (page: Page) => {
  await page.goto("/");
  await page.getByLabel("用户名", { exact: true }).fill("browser-admin");
  await page.getByLabel(/^密码/).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "作文档案", exact: true }),
  ).toBeVisible();
};
const post = async (page: Page, path: string, data: unknown) => {
  const auth = await (await page.request.get("/api/auth/status")).json();
  const result = await page.request.post("/api" + path, {
    data,
    headers: {
      Origin: process.env.CLMS_TEST_BASE_URL!,
      "X-CSRF-Token": auth.csrf_token,
    },
  });
  expect(result.ok(), await result.text()).toBeTruthy();
  return result.json();
};
const simulate = (secret: string, kind = "evaluation") =>
  JSON.parse(
    execFileSync(
      process.env.CLMS_TEST_PYTHON!,
      ["../scripts/mcp_simulate.py"],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          CLMS_TEST_MCP_SECRET: secret,
          CLMS_TEST_MCP_KIND: kind,
          CLMS_TEST_VERSION_ID: versionId,
        },
      },
    ),
  );
const proposePayload = (
  secret: string,
  kind: string,
  requestId: string,
  payload: unknown,
) =>
  JSON.parse(
    execFileSync(
      process.env.CLMS_TEST_PYTHON!,
      ["../scripts/mcp_simulate.py"],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          CLMS_TEST_MCP_SECRET: secret,
          CLMS_TEST_MCP_KIND: kind,
          CLMS_TEST_MCP_REQUEST_ID: requestId,
          CLMS_TEST_MCP_PAYLOAD: JSON.stringify(payload),
        },
      },
    ),
  );
const capture = async (page: Page, name: string) => {
  await expect(
    page.getByRole("status").filter({ hasText: "正在加载…" }),
  ).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.waitForFunction(() =>
    Array.from(
      document.querySelectorAll<HTMLImageElement>(".viewer-canvas img"),
    ).every((image) => image.complete && image.naturalWidth > 0),
  );
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => window.scrollTo({ top: 0 }));
  await page.screenshot({ path: join(evidence, name), fullPage: true });
};

// All fixtures are synthetic; no production account, token or private essay is used.
test("F01–F08 original → official MCP proposal → human review → revision and new attempt", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByLabel("用户名", { exact: true }).fill("browser-admin");
  await page.getByLabel(/^密码/).fill(password);
  await page
    .getByLabel("初始化令牌")
    .fill(process.env.CLMS_TEST_BOOTSTRAP_TOKEN!);
  await page.getByRole("button", { name: "创建管理员", exact: true }).click();
  await expect(page.getByText("还没有作文档案", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "分类管理", exact: true }).click();
  await expect(
    page.getByText("还没有自定义分类", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /创建分类/ })
    .first()
    .click();
  await page.getByLabel("分类名称").fill("生活观察");
  await page.getByLabel("适用语言").selectOption("all");
  await page.getByRole("button", { name: "保存分类", exact: true }).click();
  await expect(page.getByRole("heading", { name: "生活观察" })).toBeVisible();

  await page.getByRole("link", { name: "作文档案", exact: true }).click();
  await page
    .getByRole("link", { name: /新建作文 \/ 上传原稿/ })
    .first()
    .click();
  await page.getByLabel("题目标题").fill("A place I remember");
  await page
    .getByRole("combobox", { name: "语言", exact: true })
    .selectOption("en");
  await page
    .getByLabel("题目说明")
    .fill("Describe a place and explain why you remember it.");
  await page.getByLabel("生活观察", { exact: true }).check();
  await page
    .getByLabel("作文原稿", { exact: true })
    .setInputFiles([process.env.CLMS_TEST_IMAGE!, process.env.CLMS_TEST_PDF!]);
  await expect(
    page.getByRole("img", { name: "作文原稿第 3 页", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "第 1 页下移", exact: true }).click();
  await page.getByRole("button", { name: "第 1 页旋转", exact: true }).click();
  const saving = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/submissions") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "保存并归档", exact: true }).click();
  const saved = await (await saving).json();
  promptId = saved.prompt_id;
  versionId = saved.version_id;
  await expect(
    page.getByRole("heading", { name: "A place I remember", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "第 1 稿", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".viewer-canvas img").first()).toBeVisible();
  await page.getByRole("button", { name: "放大", exact: true }).click();
  await expect(page.getByLabel("缩放比例")).toHaveText("125%");
  await page.getByRole("button", { name: "适宽", exact: true }).click();
  await page.getByLabel("稿件页", { exact: true }).selectOption("2");
  await capture(page, "F02-mixed-manuscript.png");

  const key = await post(page, "/credentials", {
    name: "Browser simulated evaluator",
    scopes: ["archive.read", "media.read", "proposals.write"],
  });
  const proposal = simulate(key.secret);
  expect(proposal.status).toBe("pending");
  reviewId = proposal.id;
  const before = await (
    await page.request.get("/api/versions/" + versionId)
  ).json();
  expect(before.evaluations).toHaveLength(0);
  await page.goto("/#/reviews?id=" + reviewId);
  await expect(
    page.getByRole("heading", { name: "作文评价", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "修订提案", exact: true }).click();
  await page
    .getByRole("textbox", { name: "总体评价", exact: true })
    .fill("人工核对后的模拟评价，归属当前精确稿件。");
  await expect(
    page.getByRole("button", { name: "通过并入档", exact: true }),
  ).toBeDisabled();
  await page.getByRole("link", { name: "作文档案", exact: true }).click();
  await page.goto("/#/reviews?id=" + reviewId);
  await expect(
    page.getByRole("textbox", { name: "总体评价", exact: true }),
  ).toHaveValue("人工核对后的模拟评价，归属当前精确稿件。");
  await page.reload();
  await expect(
    page.getByRole("textbox", { name: "总体评价", exact: true }),
  ).toHaveValue("人工核对后的模拟评价，归属当前精确稿件。");
  await page.route(
    "**/api/reviews/" + reviewId + "/revise",
    (route) => route.abort("failed"),
    { times: 1 },
  );
  await page.getByRole("button", { name: "保存修订", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "总体评价", exact: true }),
  ).toHaveValue("人工核对后的模拟评价，归属当前精确稿件。");
  await page.getByRole("button", { name: "保存修订", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "通过并入档", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("heading", { name: "有效提案预览", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "目标原稿", exact: true }),
  ).toBeVisible();
  await capture(page, "F04-review.png");
  await page.getByRole("button", { name: "通过并入档", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "真实执行结果", exact: true }),
  ).toBeVisible();
  const after = await (
    await page.request.get("/api/versions/" + versionId)
  ).json();
  expect(after.evaluations).toHaveLength(1);
  expect(after.evaluations[0].version_id).toBe(versionId);
  expect(after.evaluations[0].payload.summary).toContain("人工核对");
  expect(
    await page.evaluate(() => (window as unknown as { __xss?: number }).__xss),
  ).toBeUndefined();

  await page.getByRole("link", { name: "打开对应档案", exact: true }).click();
  await expect(
    page.getByText("人工核对后的模拟评价，归属当前精确稿件。", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "上传修改稿", exact: true }).click();
  await page
    .getByLabel("作文原稿", { exact: true })
    .setInputFiles(process.env.CLMS_TEST_IMAGE!);
  await expect(
    page.getByRole("img", { name: "作文原稿第 1 页", exact: true }),
  ).toBeVisible();
  await page.getByLabel("本次修改说明").fill("Second draft");
  await page.getByRole("button", { name: "保存并归档", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "第 2 稿", exact: true }),
  ).toBeVisible();
  await page.getByLabel("选择对比版本").selectOption({ label: "V1" });
  await expect(
    page.getByRole("region", { name: "V1 原稿", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "V2 原稿", exact: true }),
  ).toBeVisible();
  await capture(page, "F05-versions.png");
  await page.getByRole("link", { name: "重新写一篇", exact: true }).click();
  await page
    .getByLabel("作文原稿", { exact: true })
    .setInputFiles(process.env.CLMS_TEST_IMAGE!);
  await expect(
    page.getByRole("img", { name: "作文原稿第 1 页", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "保存并归档", exact: true }).click();
  await expect(page.getByRole("tab", { name: /第 2 次写作/ })).toBeVisible();
  await page.getByRole("tab", { name: /第 2 次写作/ }).click();
  await expect(
    page.getByRole("heading", { name: "第 1 稿", exact: true }),
  ).toBeVisible();

  const categoryProposal = simulate(key.secret, "category");
  await page.goto("/#/reviews?id=" + categoryProposal.id);
  await expect(
    page.getByRole("heading", { name: "新建分类", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "通过并入档", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "真实执行结果", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "分类管理", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "MCP 模拟分类", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "作文档案", exact: true }).click();
  await page
    .getByRole("group", { name: "筛选语言", exact: true })
    .getByRole("button", { name: "英语", exact: true })
    .click();
  await page.getByLabel("筛选分类").selectOption({ label: "生活观察" });
  await page.getByLabel("搜索作文").fill("remember");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "A place I remember", exact: true }),
  ).toBeVisible();
  await capture(page, "F08-archive.png");
  expect(errors).toEqual([]);
});

test("T33 dirty submission restores after reload and history navigation", async ({
  page,
}) => {
  page.on("dialog", (dialog) => dialog.accept());
  await login(page);
  await page.goto("/#/submit");
  await page.getByLabel("题目标题").fill("Unsubmitted draft");
  await page
    .getByLabel("题目说明")
    .fill("Retained locally through route and refresh");
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await page.goBack();
  await expect(page.getByLabel("题目标题")).toHaveValue("Unsubmitted draft");
  await page.reload();
  await expect(page.getByLabel("题目说明")).toHaveValue(
    "Retained locally through route and refresh",
  );
});

test("T34 desktop/tablet/phone light and dark no horizontal overflow", async ({
  page,
}) => {
  await login(page);
  const prompts = await (await page.request.get("/api/prompts?limit=1")).json();
  const reviews = await (
    await page.request.get("/api/reviews?status=&limit=1")
  ).json();
  expect(prompts.items.length).toBeGreaterThan(0);
  expect(reviews.items.length).toBeGreaterThan(0);
  // Reuse the exact evaluated manuscript, rather than whichever proposal was last created.
  expect(promptId).not.toBe("");
  expect(versionId).not.toBe("");
  expect(reviewId).not.toBe("");
  for (const theme of ["light", "dark"]) {
    await page.goto("/#/settings");
    await page
      .getByRole("combobox", { name: "主题", exact: true })
      .selectOption(theme);
    for (const [width, height] of [
      [1440, 900],
      [1280, 800],
      [800, 1280],
      [390, 844],
      [320, 740],
    ]) {
      await page.setViewportSize({ width, height });
      for (const [name, route] of [
        ["archive", "/#/archive"],
        ["detail", "/#/prompt/" + promptId + "?version=" + versionId],
        ["review", "/#/reviews?id=" + reviewId],
      ]) {
        await page.goto(route);
        await expect(page.locator("main")).toBeVisible();
        if (name === "archive") {
          await expect(
            page
              .locator(".archive-card")
              .filter({ hasText: "A place I remember" }),
          ).toBeVisible();
          await expect(
            page.getByRole("option", { name: "生活观察", exact: true }),
          ).toBeAttached();
        } else if (name === "detail") {
          await expect(
            page.getByRole("heading", { name: "第 1 稿", exact: true }),
          ).toBeVisible();
          await expect(
            page.locator(".viewer-canvas img").first(),
          ).toBeVisible();
          if (width <= 760) {
            await page
              .getByRole("group", { name: "阅读面板" })
              .getByRole("button", { name: "评价", exact: true })
              .click();
            await expect(page.locator(".reading-paper")).toBeHidden();
          }
          await expect(
            page.getByText("人工核对后的模拟评价，归属当前精确稿件。", {
              exact: true,
            }),
          ).toBeVisible();
        } else {
          await expect(
            page.getByRole("region", { name: "目标原稿", exact: true }),
          ).toBeVisible();
          if (width <= 1160) {
            await page
              .getByRole("group", { name: "阅读面板" })
              .getByRole("button", { name: "评价", exact: true })
              .click();
            await expect(page.locator(".reading-paper")).toBeHidden();
          }
          await expect(
            page.getByRole("heading", { name: "有效提案预览", exact: true }),
          ).toBeVisible();
          await expect(
            page.getByRole("heading", { name: "真实执行结果", exact: true }),
          ).toBeVisible();
          await expect(
            page.getByText("人工核对后的模拟评价，归属当前精确稿件。", {
              exact: true,
            }),
          ).toBeVisible();
        }
        await expect(
          page.getByRole("status").filter({ hasText: "正在加载…" }),
        ).toHaveCount(0);
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth + 1,
          ),
          `${theme} ${width} ${name}`,
        ).toBeTruthy();
        await capture(page, `${theme}-${width}x${height}-${name}.png`);
      }
    }
  }
});

test("Book-page identity, mobile feedback location, exact-version comparison and frozen requirements", async ({
  page,
  browser,
}) => {
  await login(page);
  const icon = await page.request.get("/icons/clms-icon.svg");
  expect(icon.ok()).toBeTruthy();
  expect(icon.headers()["content-type"]).toContain("image/svg+xml");
  const brand = page.locator(".brand-icon");
  await expect(brand).toBeVisible();
  expect(
    await brand.evaluate(
      (image: HTMLImageElement) => image.complete && image.naturalWidth > 0,
    ),
  ).toBeTruthy();
  for (const file of ["clms-icon.ico", "apple-touch-icon.png"]) {
    const response = await page.request.get("/icons/" + file);
    expect(response.ok()).toBeTruthy();
    expect((await response.body()).length).toBeGreaterThan(100);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/prompt/" + promptId + "?version=" + versionId);
  await expect(
    page.getByRole("region", { name: "V1 原稿", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("group", { name: "阅读面板" })
    .getByRole("button", { name: "评价", exact: true })
    .click();
  const version = await (
    await page.request.get("/api/versions/" + versionId)
  ).json();
  const issue = version.evaluations[0].payload.issues[0];
  expect(issue).toBeTruthy();
  await page
    .getByRole("button", {
      name: issue.location.description || "查看对应原稿页",
      exact: true,
    })
    .click();
  await expect(page.locator(".reading-evaluation")).toBeHidden();
  await expect(
    page.getByRole("region", { name: "V1 原稿", exact: true }),
  ).toBeVisible();
  const pageIndex = version.manifest.findIndex(
    (item: { page_id: string }) => item.page_id === issue.location.page_id,
  );
  await expect(page.getByLabel("稿件页", { exact: true })).toHaveValue(
    String(pageIndex),
  );
  await capture(page, "book-mobile-location.png");
  await page.getByLabel("选择对比版本").selectOption({ label: "V2" });
  await expect(
    page.getByRole("region", { name: "V1 原稿", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "V2 原稿", exact: true }),
  ).toBeHidden();
  await page
    .getByRole("group", { name: "对比稿件" })
    .getByRole("button", { name: "V2 原稿", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "V2 原稿", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "V1 原稿", exact: true }),
  ).toBeHidden();
  await capture(page, "book-mobile-comparison.png");
  // Choosing a primary version resets comparison and keeps its own evaluations.
  await page
    .getByRole("group", { name: "稿件版本" })
    .getByRole("button", { name: /^V2/ })
    .click();
  await expect(page.getByLabel("选择对比版本")).toHaveValue("");
  await expect(page.locator(".reading-paper")).toBeVisible();
  await page
    .getByRole("group", { name: "阅读面板" })
    .getByRole("button", { name: "评价", exact: true })
    .click();
  await expect(
    page.getByText("这份稿件还没有正式评价", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("人工核对后的模拟评价，归属当前精确稿件。", { exact: true }),
  ).toHaveCount(0);

  const prompt = await (
    await page.request.get("/api/prompts/" + promptId)
  ).json();
  await post(page, "/prompts/" + promptId, {
    expected_revision: prompt.revision,
    instructions: "Current prompt changed after the original attempt.",
  });
  await page.reload();
  await page.locator(".prompt-material > summary").click();
  await expect(
    page.getByText("Describe a place and explain why you remember it.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Current prompt changed after the original attempt.", {
      exact: true,
    }),
  ).toHaveCount(0);

  // Synthetic records make the two-column archive and language filtering inspectable.
  const asset = await (
    await page.request.get("/api/assets/" + version.manifest[0].asset_id)
  ).json();
  for (const [title, language, instructions] of [
    [
      "在平凡中发现光",
      "zh",
      "从日常生活中的一次发现出发，写下让你触动的人与事。",
    ],
    ["把生活写成一封信", "zh", "给未来的自己写一封信，保留此刻的观察与思考。"],
    [
      "A small act of kindness",
      "en",
      "Tell a story about kindness and the change it brought.",
    ],
  ]) {
    await post(page, "/submissions", {
      prompt: { title, language, instructions },
      pages: [{ page_id: asset.pages[0].page_id, rotation: 0 }],
      written_at: "2026-10-10",
    });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/#/settings");
  await page
    .getByRole("combobox", { name: "主题", exact: true })
    .selectOption("light");
  await page.goto("/#/archive");
  await expect(page.locator(".archive-card")).toHaveCount(4);
  const cards = await page
    .locator(".archive-card")
    .evaluateAll((items) =>
      items.map((item) => item.getBoundingClientRect().toJSON()),
    );
  expect(cards[0].top).toBe(cards[1].top);
  expect(cards[1].left).toBeGreaterThan(cards[0].right);
  await capture(page, "book-archive.png");
  await page
    .getByRole("group", { name: "筛选语言" })
    .getByRole("button", { name: "语文", exact: true })
    .click();
  await expect(page.locator(".archive-card")).toHaveCount(2);
  await page.getByRole("button", { name: "清除筛选", exact: true }).click();
  await expect(page.locator(".archive-card")).toHaveCount(4);
  await page.goto("/#/prompt/" + promptId + "?version=" + versionId);
  const portraitPage = version.manifest.findIndex(
    (item: { rotation: number; source_page: number }) =>
      item.rotation === 0 && item.source_page === 1,
  );
  await page
    .getByLabel("稿件页", { exact: true })
    .selectOption(String(portraitPage));
  await capture(page, "book-detail.png");
  await page.goto("/#/reviews?id=" + reviewId);
  await page
    .getByLabel("稿件页", { exact: true })
    .selectOption(String(portraitPage));
  await capture(page, "book-review.png");
  const credential = await post(page, "/credentials", {
    name: "Mobile browser simulated evaluator",
    scopes: ["archive.read", "media.read", "proposals.write"],
  });
  const pendingReview = simulate(credential.secret);
  const touchContext = await browser.newContext({
    baseURL: process.env.CLMS_TEST_BASE_URL,
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    storageState: await page.context().storageState(),
  });
  try {
    const touch = await touchContext.newPage();
    await touch.goto("/#/reviews?id=" + pendingReview.id);
    await expect(
      touch.getByRole("region", { name: "目标原稿", exact: true }),
    ).toBeVisible();
    const panels = touch.getByRole("group", { name: "阅读面板" });
    await panels.getByRole("button", { name: "评价", exact: true }).click();
    await touch.getByRole("button", { name: "修订提案", exact: true }).click();
    await touch
      .getByRole("textbox", { name: "总体评价", exact: true })
      .fill("窄屏人工修订：切换原稿后仍保留输入。");
    await panels.getByRole("button", { name: "原稿", exact: true }).click();
    await panels.getByRole("button", { name: "评价", exact: true }).click();
    await expect(
      touch.getByRole("textbox", { name: "总体评价", exact: true }),
    ).toHaveValue("窄屏人工修订：切换原稿后仍保留输入。");
    await expect(
      touch.getByRole("button", { name: "通过并入档", exact: true }),
    ).toBeDisabled();
    await touch.getByRole("button", { name: "保存修订", exact: true }).click();
    await expect(
      touch.getByRole("heading", { name: "有效提案预览", exact: true }),
    ).toBeVisible();
    await expect(
      touch.getByRole("button", { name: "通过并入档", exact: true }),
    ).toBeEnabled();
    const controlHeight = await panels
      .getByRole("button", { name: "评价", exact: true })
      .evaluate((button) => button.getBoundingClientRect().height);
    expect(controlHeight).toBeGreaterThanOrEqual(44);
    await touch
      .getByRole("button", { name: "第一页面中部", exact: true })
      .click();
    await expect(
      touch.getByRole("group", { name: "原稿阅读区", exact: true }),
    ).toBeFocused();
    const positions = await touch.evaluate(() => ({
      headerBottom: document.querySelector(".sidebar")!.getBoundingClientRect()
        .bottom,
      paperTop: document
        .querySelector(".reading-paper")!
        .getBoundingClientRect().top,
    }));
    expect(positions.paperTop).toBeGreaterThanOrEqual(positions.headerBottom);
    await touch
      .getByLabel("稿件页", { exact: true })
      .selectOption(String(portraitPage));
    await touch.screenshot({
      path: join(evidence, "book-mobile-reader-viewport.png"),
    });
    await panels.getByRole("button", { name: "评价", exact: true }).click();
    await capture(touch, "book-mobile-review.png");
  } finally {
    await touchContext.close();
  }
  await page.goto("/#/reviews?id=" + pendingReview.id);
  await expect(page.locator(".review-queue .queue-item")).toHaveCount(1);
  await page
    .getByLabel("稿件页", { exact: true })
    .selectOption(String(portraitPage));
  await capture(page, "book-review-pending.png");
});

test("Review draft exposes actual actions, missing materials, proposed pages and touch help", async ({
  page,
  browser,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page);
  const key = await post(page, "/credentials", {
    name: "Review UI synthetic client",
    scopes: ["archive.read", "media.read", "proposals.write"],
  });
  const parent = await (
    await page.request.get("/api/versions/" + versionId)
  ).json();
  const attempt = await (
    await page.request.get("/api/attempts/" + parent.attempt_id)
  ).json();
  const incoming = { page_id: parent.manifest[2].page_id, rotation: 180 };
  const textPrompt = proposePayload(key.secret, "prompt", "ui-text-prompt", {
    action: "create",
    title: "熟悉的陌生地",
    language: "zh",
    instructions:
      "阅读下面的材料，根据要求写作。\n在很多文学作品中，“县城”“老家”常被描绘成“熟悉的陌生地”。你的经历中，可能也有某个熟悉的地方，如今变得有些陌生；这种变化背后，又有着深层的原因。\n请以“熟悉的陌生地”为题，写一篇记叙文。",
    requirements:
      "选准角度，确定立意，明确文体；不要套作，不得抄袭；不少于 800 字。",
    source_note:
      "合成界面样例。试卷总分为 60 分，未提供具体评分细则；本提案仅录入题目文字，未附试卷原图。",
  });
  const materialPrompt = proposePayload(
    key.secret,
    "prompt",
    "ui-material-prompt",
    {
      action: "create",
      title: "附材料的题目（合成）",
      language: "zh",
      materials: [
        incoming,
        { page_id: parent.manifest[0].page_id, rotation: 0 },
      ],
    },
  );
  const revision = proposePayload(
    key.secret,
    "revision",
    "ui-incoming-revision",
    {
      attempt_id: parent.attempt_id,
      parent_version_id: parent.id,
      pages: [incoming],
      change_note: "调整结尾，待入档的是这份 1 页修改稿。",
    },
  );
  const submission = proposePayload(
    key.secret,
    "submission",
    "ui-combined-submission",
    {
      prompt: {
        title: "一次新的观察（合成）",
        language: "zh",
        instructions: "记录一次生活观察。",
      },
      inline_categories: [
        {
          name: "草稿中的生活观察",
          language_scope: "zh",
          description: "随这项提案一起创建",
        },
      ],
      pages: [incoming],
      duration_minutes: 35,
      reflection: "下次多写具体细节。",
    },
  );
  const reflection = proposePayload(key.secret, "reflection", "ui-reflection", {
    attempt_id: attempt.id,
    expected_revision: attempt.revision,
    reflection: "新的写作反思：先观察，再表达。",
  });
  const category = proposePayload(key.secret, "category", "ui-category", {
    action: "create",
    name: "审稿草稿分类",
    language_scope: "all",
  });
  const pending = await (
    await page.request.get("/api/reviews?status=pending&limit=1")
  ).json();
  await page.goto("/#/reviews?id=" + textPrompt.id);
  await expect(
    page.getByRole("heading", { name: "新建题目", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".proposal-content")).toContainText(
    "不少于 800 字",
  );
  await expect(page.getByText("未附原始材料图", { exact: true })).toBeVisible();
  await expect(page.getByText("未提供评分细则", { exact: true })).toBeVisible();
  await expect(page.locator(".review-proposal pre")).toBeHidden();
  await expect(page.locator(".review-nav-badge")).toHaveText(
    String(pending.total),
  );
  await capture(page, "review-draft-desktop.png");
  await page.getByRole("button", { name: "题目材料说明", exact: true }).click();
  await expect(page.getByRole("tooltip")).toContainText("试卷原图已经上传");
  await capture(page, "review-draft-help.png");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip")).toHaveCount(0);

  await page.goto("/#/reviews?id=" + materialPrompt.id);
  const materials = page.getByRole("region", { name: "题目材料", exact: true });
  await expect(materials).toBeVisible();
  await expect(materials.locator("img")).toHaveAttribute(
    "src",
    new RegExp(incoming.page_id + ".*rotation=180"),
  );
  await page.getByLabel("稿件页", { exact: true }).selectOption("1");
  await capture(page, "review-draft-materials.png");
  await page.goto("/#/reviews?id=" + revision.id);
  const paper = page.getByRole("region", { name: "待入档修改稿", exact: true });
  await expect(paper).toBeVisible();
  await expect(paper.locator("img")).toHaveAttribute(
    "src",
    new RegExp(incoming.page_id + ".*rotation=180"),
  );
  await expect(paper.getByRole("option")).toHaveCount(1);
  await capture(page, "review-draft-revision.png");
  await page.goto("/#/reviews?id=" + submission.id);
  await expect(
    page.getByRole("heading", { name: "同时新建的题目", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("草稿中的生活观察", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("35 分钟", { exact: true })).toBeVisible();
  await page.goto("/#/reviews?id=" + reflection.id);
  await expect(
    page.getByText("新的写作反思：先观察，再表达。", { exact: true }),
  ).toBeVisible();
  await page.goto("/#/reviews?id=" + category.id);
  await expect(page.getByText("中英通用", { exact: true })).toBeVisible();

  const touchContext = await browser.newContext({
    baseURL: process.env.CLMS_TEST_BASE_URL,
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    storageState: await page.context().storageState(),
  });
  try {
    const touch = await touchContext.newPage();
    await touch.goto("/#/reviews?id=" + textPrompt.id);
    const help = touch.getByRole("button", {
      name: "题目材料说明",
      exact: true,
    });
    await help.tap();
    await expect(touch.getByRole("tooltip")).toBeVisible();
    const box = await touch.getByRole("tooltip").boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    // Measure after the brief pointer-down scale has returned to its resting size.
    await expect
      .poll(() =>
        help.evaluate((button) => button.getBoundingClientRect().height),
      )
      .toBeGreaterThanOrEqual(44);
    await touch.getByRole("button", { name: "刷新队列", exact: true }).tap();
    await expect(touch.getByRole("tooltip")).toHaveCount(0);
    await capture(touch, "review-draft-mobile.png");
    await touch.setViewportSize({ width: 320, height: 740 });
    await capture(touch, "review-draft-narrow.png");
    expect(
      await touch.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBeTruthy();
    await touch.goto("/#/reviews?id=" + materialPrompt.id);
    await expect(
      touch.getByRole("region", { name: "题目材料", exact: true }),
    ).toBeVisible();
    await touch
      .getByRole("group", { name: "阅读面板" })
      .getByRole("button", { name: "提案", exact: true })
      .tap();
    await expect(
      touch.getByRole("heading", { name: "有效提案预览", exact: true }),
    ).toBeVisible();
  } finally {
    await touchContext.close();
  }

  await page.goto("/#/reviews?id=" + textPrompt.id);
  await page.getByRole("button", { name: "驳回", exact: true }).click();
  await expect(page.locator(".review-nav-badge")).toHaveText(
    String(pending.total - 1),
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "新建题目", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("这项提案未执行", { exact: true })).toBeVisible();
  await page.getByLabel("审核状态", { exact: true }).selectOption("processed");
  await expect(
    page.locator(".review-queue").getByText("熟悉的陌生地", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("MCP uploads images and PDF, previews pending originals and archives after Web approval", async ({
  page,
}) => {
  await login(page);
  const key = await post(page, "/credentials", {
    name: "Attachment upload synthetic client",
    scopes: ["archive.read", "media.read", "proposals.write"],
  });
  const image = simulate(key.secret, "upload");
  const pdf = simulate(key.secret, "upload-pdf");
  expect(image.status).toBe("staged");
  expect(pdf.page_count).toBe(2);
  const pages = [...image.pages, ...pdf.pages].map(
    (item: { page_id: string }) => ({ page_id: item.page_id }),
  );
  const proposal = proposePayload(
    key.secret,
    "submission",
    "browser-mcp-upload",
    {
      prompt: {
        title: "通过 MCP 上传的作文",
        language: "en",
        instructions: "Describe a place you remember.",
      },
      pages,
      duration_minutes: 25,
    },
  );
  expect(proposal.status).toBe("pending");
  await page.goto("/#/reviews?id=" + proposal.id);
  const original = page.getByRole("region", {
    name: "待入档原稿",
    exact: true,
  });
  await expect(original).toBeVisible();
  await expect(original.locator("img")).toHaveAttribute(
    "src",
    new RegExp(image.pages[0].page_id),
  );
  await expect(page.getByText("25 分钟", { exact: true })).toBeVisible();
  await capture(page, "mcp-upload-pending.png");
  await page.getByRole("button", { name: "通过并入档", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "真实执行结果", exact: true }),
  ).toBeVisible();
  const approved = await (
    await page.request.get("/api/reviews/" + proposal.id)
  ).json();
  expect(approved.status).toBe("applied");
  await page.goto(approved.result.path);
  await expect(
    page.getByRole("region", { name: "V1 原稿", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByLabel("稿件页", { exact: true }).getByRole("option"),
  ).toHaveCount(3);
  await page.getByLabel("稿件页", { exact: true }).selectOption("2");
  await expect(page.locator(".viewer-canvas img").first()).toHaveAttribute(
    "src",
    new RegExp(pdf.pages[1].page_id),
  );
  await capture(page, "mcp-upload-archived.png");
});
