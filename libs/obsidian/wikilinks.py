"""Markdown → Obsidian wikilink converter, plus header / footer helpers.

The wiki articles under ``.context/wiki/`` are written in plain markdown so
they remain portable for LLM consumers (a single ``cat`` of the directory
gives a coherent prose corpus). Obsidian, however, needs ``[[wikilinks]]``
to drive its graph view and backlink pane — that's the whole point of
mirroring the wiki into the vault.

This module is the bridge:

* :func:`convert_md_links_to_wikilinks` rewrites ``[text](modules/foo.md)``
  → ``[[modules/foo|text]]`` in a single conservative pass. External
  links, images, in-page anchors, and code-fenced blocks are left
  untouched (false negatives are far cheaper than false positives — a
  silently rewritten external URL would break navigation).
* :func:`make_index_header` and :func:`make_wiki_footer` produce small
  navigation snippets that are *prepended* to ``INDEX.md`` and *appended*
  to every other mirrored article so the user can pivot between the
  prose wiki, the project ``Home``, and the auto-generated ``Modules/``
  tree without leaving the vault.

The converter is deliberately string-only — no markdown parser
dependency. A one-pass regex over each non-fenced line covers every link
shape the wiki generator emits today, and the test suite under
``tests/unit/obsidian/test_wikilinks.py`` pins the edge cases.
"""

from __future__ import annotations

import re

# ``[text](target)`` — the leading negative lookbehind excludes ``![alt](src)``
# image syntax, which has different semantics and must never become a
# wikilink (Obsidian images are ``![[file.png]]``, not ``[[file.png]]``).
_MD_LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)\s]+)\)")

# Detect the start (and end) of a fenced code block per CommonMark. Both
# ``` and ~~~ are valid fence markers; we toggle a flag rather than
# trying to track nesting because CommonMark forbids it inside a fence.
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Things that look like links but must NEVER be rewritten:
# * absolute URLs (``http://``, ``https://``, ``ftp://``, ``ssh://``, ...)
# * common URI schemes (``mailto:``, ``tel:``)
# * in-page anchors (``#section``)
_EXTERNAL_TARGET_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|mailto:|tel:|#)", re.IGNORECASE)


def convert_md_links_to_wikilinks(content: str) -> str:
    r"""Rewrite portable markdown links into Obsidian wikilinks.

    Rules (each one is pinned by a test in
    ``tests/unit/obsidian/test_wikilinks.py``):

    * ``[text](modules/foo.md)`` → ``[[modules/foo|text]]``
    * ``[text](modules/foo)`` → ``[[modules/foo|text]]`` (extension optional)
    * ``[text](modules/foo.md#section)`` → ``[[modules/foo#section|text]]``
    * ``[text](https://...)`` — left as-is (would 404 in vault)
    * ``[text](mailto:...)`` / ``[text](#anchor)`` — left as-is
    * ``![alt](path.png)`` — left as-is (image syntax)
    * ``[text](modules/foo.md)`` *inside a* ``\`\`\`...\`\`\`` *or* ``~~~...~~~``
      *fence* — left as-is (it's documentation of markdown, not a link)

    The function is idempotent: running it twice yields the same output
    because ``[[wikilinks]]`` don't match ``[text](url)``.

    Trailing newline (or its absence) is preserved verbatim — wiki
    articles always end in ``\n`` and the atomic-write path on the
    publisher relies on that.
    """
    if not content:
        return content

    # Split keeping line endings so we can reassemble byte-for-byte.
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    in_fence = False

    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        out.append(_MD_LINK_RE.sub(_rewrite_one_link, line))

    return "".join(out)


def _rewrite_one_link(match: re.Match[str]) -> str:
    """Per-link rewrite callback for :func:`convert_md_links_to_wikilinks`."""
    text, target = match.group(1), match.group(2)

    # External / anchor / scheme links: keep the original markdown verbatim.
    if _EXTERNAL_TARGET_RE.match(target):
        return match.group(0)

    # Split off ``#section`` so we can drop ``.md`` from the path while
    # preserving the heading anchor on the wikilink target.
    if "#" in target:
        path, _, fragment = target.partition("#")
        wiki_target = _strip_md_extension(path) + "#" + fragment
    else:
        wiki_target = _strip_md_extension(target)

    # ``[[target|display]]`` is the canonical aliased wikilink form.
    return f"[[{wiki_target}|{text}]]"


def _strip_md_extension(path: str) -> str:
    """Drop a trailing ``.md`` (case-insensitive) — Obsidian wikilinks
    resolve without it."""
    if path.lower().endswith(".md"):
        return path[: -len(".md")]
    return path


def make_wiki_footer(*, project_name: str, module_short: str | None) -> str:
    """Build the ``## See also`` footer appended to mirrored wiki articles.

    Always links back to the project ``Home`` and the ``Wiki/INDEX`` so
    the user can climb out of any article in one click. When
    ``module_short`` is provided (the first dash-separated segment of
    the article slug, e.g. ``apps`` for ``apps-cli.md``) the footer also
    links to the auto-generated ``Modules/<short>`` page so the user can
    pivot from the prose wiki to the structural stats.

    Returned string starts with a ``\\n---\\n`` separator so it can be
    concatenated directly to a wiki article body without worrying about
    whether the body ends in a trailing newline.
    """
    lines = [
        "",
        "---",
        "",
        "## See also",
        "",
        f"- [[Projects/{project_name}/Home|Project home]]",
        f"- [[Projects/{project_name}/Wiki/INDEX|Wiki index]]",
    ]
    if module_short:
        lines.append(
            f"- [[Projects/{project_name}/Modules/{module_short}|Module stats: {module_short}]]"
        )
    lines.append("")
    return "\n".join(lines)


def make_index_header(*, project_name: str) -> str:
    """Build the navigation blockquote prepended to the mirrored ``INDEX.md``.

    A single-line blockquote keeps the original H1 visible at the top of
    the rendered note while still giving the user a one-click path to
    ``Home``, the auto-generated ``Modules`` folder, and the
    ``Recent Changes`` page.

    Returned string ends in ``\\n\\n`` so the original INDEX content can
    be appended verbatim without losing the blank line separator markdown
    needs between the blockquote and the H1.
    """
    return (
        f"> Navigation: [[Projects/{project_name}/Home|Project home]] · "
        f"[[Projects/{project_name}/Modules|Modules]] · "
        f"[[Projects/{project_name}/Recent Changes|Recent changes]]\n\n"
    )
