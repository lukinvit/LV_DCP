import * as vscode from "vscode";
import { PackResult } from "./ctxClient";

export class PackTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly filePath?: string,
    ) {
        super(label, vscode.TreeItemCollapsibleState.None);
        if (filePath) {
            this.command = {
                command: "vscode.open",
                title: "Open File",
                arguments: [vscode.Uri.file(filePath)],
            };
            this.iconPath = new vscode.ThemeIcon("file");
        } else {
            this.iconPath = new vscode.ThemeIcon("symbol-method");
        }
    }
}

export class PackProvider implements vscode.TreeDataProvider<PackTreeItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<
        PackTreeItem | undefined
    >();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    private items: PackTreeItem[] = [];

    update(result: PackResult, projectRoot: string): void {
        this.items = [];
        for (const file of result.files) {
            this.items.push(new PackTreeItem(file, `${projectRoot}/${file}`));
        }
        for (const sym of result.symbols.slice(0, 15)) {
            this.items.push(new PackTreeItem(`\u27E1 ${sym}`));
        }
        this._onDidChangeTreeData.fire(undefined);
    }

    getTreeItem(element: PackTreeItem): PackTreeItem {
        return element;
    }

    getChildren(): PackTreeItem[] {
        return this.items;
    }
}
