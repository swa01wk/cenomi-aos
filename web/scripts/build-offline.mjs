// Build without Vite: esbuild bundles src/ into dist/. For sandboxes where npm install is blocked but
// react, react-dom and esbuild exist in a shared node_modules (set NODE_MODULES to point at it).
// Normal machines use `npm run build`.
import { createRequire } from "node:module";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const modules = process.env.NODE_MODULES ?? join(root, "node_modules");
const require = createRequire(join(modules, "noop.js"));
const esbuild = require("esbuild");

const out = join(root, "dist");
rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "assets"), { recursive: true });

await esbuild.build({
  entryPoints: [join(root, "src/main.tsx")],
  bundle: true,
  minify: true,
  sourcemap: true,
  format: "esm",
  target: "es2022",
  jsx: "automatic",
  nodePaths: [modules],
  define: { "process.env.NODE_ENV": '"production"' },
  outfile: join(out, "assets/app.js"),
  logLevel: "info",
});

const html = readFileSync(join(root, "index.html"), "utf8")
  .replace('<script type="module" src="/src/main.tsx"></script>',
           '<link rel="stylesheet" href="/assets/app.css" />\n    <script type="module" src="/assets/app.js"></script>');
writeFileSync(join(out, "index.html"), html);
console.log("built web/dist");
