import * as vscode from "vscode";
import { getContextPack } from "./ctxClient";
import { PackProvider } from "./packProvider";

let statusBarItem: vscode.StatusBarItem;

export function activate(context: vscode.ExtensionContext): void {
    const packProvider = new PackProvider();
    vscode.window.registerTreeDataProvider("lvdcp.packResults", packProvider);

    // Status bar
    statusBarItem = vscode.window.createStatusBarItem(
        vscode.StatusBarAlignment.Left,
        50
    );
    statusBarItem.text = "$(symbol-structure) LV_DCP";
    statusBarItem.tooltip = "LV_DCP Developer Context Platform";
    statusBarItem.command = "lvdcp.getPack";
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    // Get Context Pack command
    context.subscriptions.push(
        vscode.commands.registerCommand("lvdcp.getPack", async () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (!workspaceFolder) {
                vscode.window.showErrorMessage("No workspace folder open.");
                return;
            }

            const query = await vscode.window.showInputBox({
                prompt: "Enter your context query",
                placeHolder: "e.g., how does authentication work?",
            });
            if (!query) {
                return;
            }

            try {
                statusBarItem.text = "$(loading~spin) LV_DCP...";
                const result = await getContextPack(
                    workspaceFolder.uri.fsPath,
                    query
                );
                packProvider.update(result, workspaceFolder.uri.fsPath);
                statusBarItem.text = `$(symbol-structure) LV_DCP [${result.files.length} files]`;
            } catch (err: unknown) {
                const message =
                    err instanceof Error ? err.message : String(err);
                vscode.window.showErrorMessage(`LV_DCP: ${message}`);
                statusBarItem.text = "$(symbol-structure) LV_DCP";
            }
        })
    );

    // Show Impact command
    context.subscriptions.push(
        vscode.commands.registerCommand("lvdcp.showImpact", async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showErrorMessage("No active file.");
                return;
            }
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (!workspaceFolder) {
                return;
            }

            const relativePath = vscode.workspace.asRelativePath(
                editor.document.uri
            );
            try {
                const result = await getContextPack(
                    workspaceFolder.uri.fsPath,
                    `impact analysis for ${relativePath}`,
                    "edit"
                );
                packProvider.update(result, workspaceFolder.uri.fsPath);
            } catch (err: unknown) {
                const message =
                    err instanceof Error ? err.message : String(err);
                vscode.window.showErrorMessage(`LV_DCP: ${message}`);
            }
        })
    );
}

export function deactivate(): void {
    statusBarItem?.dispose();
}
