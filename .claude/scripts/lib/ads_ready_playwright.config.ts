import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  fullyParallel: false,
  workers: 1,
  reporter: [["json", { outputFile: "ads-ready-report.json" }]],
  outputDir: ".",
  projects: [{ name: "chromium-only", use: { browserName: "chromium" } }],
});
