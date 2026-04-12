"""Post-scan: link docs/spec files to code modules they describe."""

from __future__ import annotations

import re

from libs.core.entities import Relation, RelationType

# Match file paths in markdown content (e.g., `libs/retrieval/pipeline.py`, src/web/app.py)
_FILE_REF_RE = re.compile(
    r'(?:^|\s|`|"|\()([a-z][a-z0-9_/]+\.(?:py|js|html|yaml|yml))',
    re.MULTILINE,
)
# Match Python module paths (e.g., libs.retrieval.pipeline, apps.mcp.server)
_MODULE_REF_RE = re.compile(
    r'(?:^|\s|`|"|\()((?:libs|apps|src|bot)\.[a-z][a-z0-9_.]+)',
    re.MULTILINE,
)


def extract_specifies_relations(
    docs_files: list[tuple[str, str]],  # [(path, content), ...]
    all_file_paths: set[str],
) -> list[Relation]:
    """Find file references in docs content and create specifies relations."""
    relations: list[Relation] = []
    seen: set[tuple[str, str]] = set()

    for doc_path, content in docs_files:
        # Find file path references
        for m in _FILE_REF_RE.finditer(content):
            ref = m.group(1)
            if ref in all_file_paths and ref != doc_path:
                pair = (doc_path, ref)
                if pair not in seen:
                    seen.add(pair)
                    relations.append(
                        Relation(
                            src_type="file",
                            src_ref=doc_path,
                            dst_type="file",
                            dst_ref=ref,
                            relation_type=RelationType.SPECIFIES,
                            provenance="docs_linker",
                        )
                    )

        # Find module path references (dots -> slashes)
        for m in _MODULE_REF_RE.finditer(content):
            mod = m.group(1)
            file_path = mod.replace(".", "/") + ".py"
            if file_path in all_file_paths and file_path != doc_path:
                pair = (doc_path, file_path)
                if pair not in seen:
                    seen.add(pair)
                    relations.append(
                        Relation(
                            src_type="file",
                            src_ref=doc_path,
                            dst_type="file",
                            dst_ref=file_path,
                            relation_type=RelationType.SPECIFIES,
                            provenance="docs_linker",
                        )
                    )

    return relations
