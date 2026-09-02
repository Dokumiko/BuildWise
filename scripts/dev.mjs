import { existsSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const rootDirectory = resolve(fileURLToPath(new URL("..", import.meta.url)));
const backendDirectory = resolve(rootDirectory, "backend");
const frontendDirectory = resolve(rootDirectory, "frontend");
const pythonPath = resolve(
  backendDirectory,
  process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python",
);
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const nextPackagePath = resolve(frontendDirectory, "node_modules", "next", "package.json");

if (!existsSync(pythonPath)) {
  console.error(
    "BuildWise backend virtual environment was not found. Create it in backend/.venv before running npm run dev.",
  );
  process.exit(1);
}

if (!existsSync(nextPackagePath)) {
  console.log("Installing frontend dependencies for the first local run...");
  const install = spawnSync(npmCommand, ["ci"], {
    cwd: frontendDirectory,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (install.status !== 0) {
    process.exit(install.status ?? 1);
  }
}

console.log("\nStarting BuildWise local development services:");
console.log("  Frontend: http://localhost:3000");
console.log("  Backend:  http://127.0.0.1:8000");
console.log("  API docs: http://127.0.0.1:8000/docs");
console.log("  Press Ctrl+C to stop both services.\n");

const backend = spawn(
  pythonPath,
  ["-m", "uvicorn", "app.main:app", "--app-dir", "src", "--reload", "--host", "127.0.0.1", "--port", "8000"],
  { cwd: backendDirectory, stdio: "inherit" },
);
const frontend = spawn(npmCommand, ["run", "dev"], {
  cwd: frontendDirectory,
  stdio: "inherit",
  shell: process.platform === "win32",
});

const processes = [backend, frontend];
let shuttingDown = false;

function terminateProcessTree(child) {
  if (child.exitCode !== null || child.pid === undefined) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    child.kill("SIGTERM");
  }
}

function shutdown(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of processes) terminateProcessTree(child);
  process.exitCode = exitCode;
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => shutdown());
}

for (const child of processes) {
  child.on("error", (error) => {
    console.error(`Could not start a BuildWise development service: ${error.message}`);
    shutdown(1);
  });
  child.on("exit", (code, signal) => {
    if (shuttingDown) return;
    const reason = signal ? `signal ${signal}` : `exit code ${code ?? 1}`;
    console.error(`A BuildWise development service stopped unexpectedly (${reason}).`);
    shutdown(code ?? 1);
  });
}
