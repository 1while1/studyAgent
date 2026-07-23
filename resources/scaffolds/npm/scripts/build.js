// 零依赖构建脚本：把 src/ 原样复制到 dist/。
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const src = path.join(root, "src");
const dist = path.join(root, "dist");

fs.rmSync(dist, { recursive: true, force: true });
fs.cpSync(src, dist, { recursive: true });
const files = fs.readdirSync(dist);
console.log(`build ok: ${files.length} 个文件 -> dist/（${files.join(", ")}）`);
