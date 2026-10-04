import { defineConfig } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
const root = resolve(import.meta.dirname, '..');
const python = process.env.COCKPIT_TEST_PYTHON || join(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const database = join(mkdtempSync(join(tmpdir(), 'cockpit-browser-')), 'browser.db');
export default defineConfig({
  testDir: './e2e', workers: 1, fullyParallel: false, timeout: 90000,
  use: { baseURL: 'http://127.0.0.1:8000', browserName: 'chromium',
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined },
    trace: 'retain-on-failure' },
  webServer: { command: `"${python}" -m cockpit.launch`, cwd: root,
    env: { COCKPIT_DB: database }, url: 'http://127.0.0.1:8000/health',
    reuseExistingServer: false, timeout: 30000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 80000 } },
});
