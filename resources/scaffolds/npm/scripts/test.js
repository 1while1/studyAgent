// 零依赖自测：校验源码文件齐全且占位符已替换。
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
for (const f of ["src/index.html", "src/app.js", "src/style.css",
                 "scripts/build.js", "scripts/serve.js"]) {
  assert.ok(fs.existsSync(path.join(root, f)), `缺少文件: ${f}`);
}
// 注意：令牌字面量必须动态拼接，否则脚手架的 {{name}} 替换会误改本脚本逻辑
const TOKEN = "{{" + "name" + "}}";
const html = fs.readFileSync(path.join(root, "src/index.html"), "utf-8");
assert.ok(!html.includes(TOKEN), "脚手架占位符未被替换（生成异常）");
const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf-8"));
assert.ok(pkg.scripts && pkg.scripts.build && pkg.scripts.start, "package.json scripts 不完整");
console.log("test ok: 3 项断言全部通过");
