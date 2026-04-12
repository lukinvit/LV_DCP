import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export interface PackResult {
    files: string[];
    symbols: string[];
    coverage: string;
    markdown: string;
}

export async function getContextPack(
    projectPath: string,
    query: string,
    mode: "navigate" | "edit" = "navigate"
): Promise<PackResult> {
    const { stdout } = await execFileAsync("ctx", [
        "pack",
        projectPath,
        "--query",
        query,
        "--mode",
        mode,
        "--format",
        "json",
    ], { timeout: 30000 });

    return JSON.parse(stdout);
}

export async function getInspect(projectPath: string): Promise<string> {
    const { stdout } = await execFileAsync("ctx", [
        "inspect",
        projectPath,
    ], { timeout: 15000 });
    return stdout;
}
