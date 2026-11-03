import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import http from "node:http";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { chromium } from "playwright";

const require = createRequire(import.meta.url);
const axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const viteBin = join(dirname(require.resolve("vite/package.json")), "bin", "vite.js");
const port = Number(process.env.TOWNLIGHT_RECORDS_A11Y_PORT || 4173);
const url = `http://127.0.0.1:${port}/`;
const tags = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

function waitForServer(target, timeoutMs = 30000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const req = http.get(target, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() - start > timeoutMs) {
          reject(new Error(`Timed out waiting for ${target}`));
          return;
        }
        setTimeout(check, 500);
      });
      req.setTimeout(1000, () => req.destroy());
    };
    check();
  });
}

const server = spawn(
  process.execPath,
  [viteBin, "preview", "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
  { stdio: ["ignore", "ignore", "ignore"] },
);

let browser;
try {
  await waitForServer(url);
  browser = await chromium.launch({ args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.addScriptTag({ content: axeSource });
  const results = await page.evaluate((runTags) => window.axe.run(document, {
    runOnly: { type: "tag", values: runTags },
  }), tags);
  const serious = results.violations.filter((violation) => ["critical", "serious"].includes(violation.impact));
  if (serious.length) {
    for (const violation of serious) {
      const targets = violation.nodes.slice(0, 5)
        .map((node) => `${node.target.join(" ")} html=${String(node.html || "").slice(0, 160)}`)
        .join("; ");
      console.error(`${violation.impact}: ${violation.id} - ${violation.help} targets=${targets}`);
    }
    process.exitCode = 1;
  } else {
    console.log(`a11y:ci PASS ${url} critical_or_serious=0`);
  }
} finally {
  await browser?.close();
  server.kill();
}
