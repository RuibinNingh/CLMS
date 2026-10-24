import { defineConfig } from '@playwright/test';

const evidence = process.env.CLMS_TEST_EVIDENCE || '../artifacts/browser';
export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60000,
  expect: { timeout: 10000 },
  reporter: [['list'], ['json', { outputFile: `${evidence}/playwright.json` }]],
  outputDir: `${evidence}/results`,
  use: {
    baseURL: process.env.CLMS_TEST_BASE_URL,
    browserName: 'chromium',
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'off',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {},
  },
});
