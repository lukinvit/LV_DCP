import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export interface PackResult {
    files: string[];
    symbols: string[];
    coverage: string;
    markdown: string;
}

export interface CtxConfig {
    cliPath: string;
    timeoutMs: number;
}

export async function getContextPack(
    projectPath: string,
    query: string,
    mode: "navigate" | "edit",
    config: CtxConfig,
): Promise<PackResult> {
    const { stdout } = await execFileAsync(
        config.cliPath,
        [
            "pack",
            projectPath,
            "--query",
            query,
            "--mode",
            mode,
            "--format",
            "json",
        ],
        { timeout: config.timeoutMs },
    );

    return JSON.parse(stdout);
}

export async function getInspect(
    projectPath: string,
    config: CtxConfig,
): Promise<string> {
    const { stdout } = await execFileAsync(
        config.cliPath,
        ["inspect", projectPath],
        { timeout: config.timeoutMs },
    );
    return stdout;
}
