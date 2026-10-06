// Writes the website's browser libraries to jobscraper/web/vendor/ (not committed; the website build runs this).
import { build } from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..", "jobscraper", "web", "vendor");
mkdirSync(out, { recursive: true });

await build({
  stdin: { contents: 'export { default } from "@anthropic-ai/sdk";', resolveDir: here },
  bundle: true,
  format: "esm",
  platform: "browser",
  minify: true,
  external: ["node:*"],
  outfile: join(out, "anthropic-sdk.mjs"),
  logLevel: "warning",
});
// The "legacy" build of pdf.js also works in older phone browsers.
for (const file of ["pdf.min.mjs", "pdf.worker.min.mjs"]) {
  copyFileSync(join(here, "node_modules", "pdfjs-dist", "legacy", "build", file), join(out, file));
}
console.log(`Browser libraries written to ${out}`);
