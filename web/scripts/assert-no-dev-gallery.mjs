import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const MARKER = "AOS_DEV_COMPONENTS_GALLERY_x7k9";
const dist = join(fileURLToPath(new URL(".", import.meta.url)), "..", "dist");

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.(js|css|html)$/.test(name)) out.push(p);
  }
  return out;
}

if (!existsSync(dist)) {
  console.error("dist/ missing; run vite build first");
  process.exit(1);
}

const hits = walk(dist).filter((f) => readFileSync(f, "utf8").includes(MARKER));
if (hits.length) {
  console.error("Dev gallery marker found in production bundle:", hits.join("\n"));
  process.exit(1);
}

console.log("Production bundle does not include dev gallery marker.");
