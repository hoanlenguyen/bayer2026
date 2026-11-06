// One local development entry point for the existing FastAPI and Vite apps.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const venv = path.join(root, "backend/.venv/bin/python");
const rootVenv = path.join(root, ".venv/bin/python");
const python = process.env.PYTHON_BIN || (existsSync(venv) ? venv : existsSync(rootVenv) ? rootVenv : "python");
const apiPort = process.env.BAYER_API_PORT || "8013";
const backend = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", apiPort], {cwd:path.join(root,"backend"),stdio:"inherit",env:process.env});
const frontend = spawn(process.execPath, [path.join(root,"frontend/node_modules/vite/bin/vite.js"), "--host", "0.0.0.0", ...process.argv.slice(2)], {cwd:path.join(root,"frontend"),stdio:"inherit",env:{...process.env,BAYER_API_URL:`http://127.0.0.1:${apiPort}`}});
const stop = () => { backend.kill("SIGTERM"); frontend.kill("SIGTERM"); };
for (const child of [backend, frontend]) { child.on("error", error => { console.error(error.message); stop(); process.exitCode=1; }); child.on("exit", code => { stop(); process.exitCode=code || 0; }); }
process.on("SIGINT",stop); process.on("SIGTERM",stop);
