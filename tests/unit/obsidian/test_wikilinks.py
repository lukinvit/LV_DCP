"""Tests for libs.obsidian.wikilinks — markdown → Obsidian wikilink converter.

The converter is the bridge that lets one source of truth in
``.context/wiki/`` (portable markdown for LLM consumers) render as
clickable graph-aware notes inside an Obsidian vault. The contract is
deliberately conservative: false negatives (leaving a link as plain
markdown) are far cheaper than false positives (rewriting an external
link as a non-resolvable wikilink), so each rule below is a checked
edge case, not a happy-path smoke test.
"""

from __future__ import annotations

from libs.obsidian.wikilinks import (
    convert_md_links_to_wikilinks,
    make_index_header,
    make_wiki_footer,
)


class TestConvertMdLinksToWikilinks:
    def test_relative_md_link_converted(self) -> None:
        """The flagship rewrite: INDEX-style ``[text](modules/foo.md)``."""
        src = "- [apps-cli](modules/apps-cli.md) — summary"
        out = convert_md_links_to_wikilinks(src)
        assert out == "- [[modules/apps-cli|apps-cli]] — summary"

    def test_relative_link_without_extension(self) -> None:
        """Authors sometimes drop the ``.md`` — still a wikilink."""
        src = "see [foo](modules/foo) for details"
        assert convert_md_links_to_wikilinks(src) == "see [[modules/foo|foo]] for details"

    def test_md_extension_strip_case_insensitive(self) -> None:
        """``FOO.MD`` and ``foo.Md`` strip the same way as lowercase."""
        src = "[Foo](modules/Foo.MD)"
        assert convert_md_links_to_wikilinks(src) == "[[modules/Foo|Foo]]"

    def test_external_http_link_left_alone(self) -> None:
        """External URLs must never become wikilinks — they'd 404 in vault."""
        src = "see [karpathy blog](https://karpathy.ai/wiki) for context"
        assert convert_md_links_to_wikilinks(src) == src

    def test_external_https_link_left_alone(self) -> None:
        src = "[Anthropic](https://www.anthropic.com)"
        assert convert_md_links_to_wikilinks(src) == src

    def test_mailto_link_left_alone(self) -> None:
        src = "contact [team](mailto:noreply@example.com)"
        assert convert_md_links_to_wikilinks(src) == src

    def test_image_link_left_alone(self) -> None:
        """Image syntax ``![alt](src)`` must NOT convert — image semantics differ."""
        src = "![architecture diagram](diagrams/arch.png)"
        assert convert_md_links_to_wikilinks(src) == src

    def test_anchor_only_link_left_alone(self) -> None:
        """In-page anchors ``[text](#section)`` survive as-is."""
        src = "jump to [intro](#introduction)"
        assert convert_md_links_to_wikilinks(src) == src

    def test_already_wikilink_left_alone(self) -> None:
        """Idempotent: running the converter twice yields the same output."""
        once = convert_md_links_to_wikilinks("[foo](modules/foo.md)")
        twice = convert_md_links_to_wikilinks(once)
        assert once == twice

    def test_link_with_fragment_keeps_section_in_target(self) -> None:
        """``[text](modules/foo.md#section)`` → ``[[modules/foo#section|text]]``."""
        src = "see [the rules](modules/constitution.md#rules)"
        out = convert_md_links_to_wikilinks(src)
        assert out == "see [[modules/constitution#rules|the rules]]"

    def test_multiple_links_on_one_line(self) -> None:
        src = "[a](modules/a.md) and [b](modules/b.md)"
        assert convert_md_links_to_wikilinks(src) == "[[modules/a|a]] and [[modules/b|b]]"

    def test_code_fence_content_is_not_converted(self) -> None:
        """Markdown samples inside ``` fences are documentation, not links."""
        src = (
            "Example:\n"
            "```markdown\n"
            "[click](modules/foo.md)\n"
            "```\n"
            "After fence: [real](modules/bar.md)\n"
        )
        out = convert_md_links_to_wikilinks(src)
        assert "[click](modules/foo.md)" in out  # fence body untouched
        assert "[[modules/bar|real]]" in out  # outside fence converted

    def test_tilde_fence_also_skipped(self) -> None:
        """Both ``` and ~~~ start fenced code blocks per CommonMark."""
        src = "~~~\n[skipped](modules/x.md)\n~~~\n[converted](modules/y.md)"
        out = convert_md_links_to_wikilinks(src)
        assert "[skipped](modules/x.md)" in out
        assert "[[modules/y|converted]]" in out

    def test_trailing_newline_preserved(self) -> None:
        """Wiki articles always end in \\n — the converter must not eat it."""
        src = "# title\n\n[foo](modules/foo.md)\n"
        assert convert_md_links_to_wikilinks(src).endswith("\n")

    def test_no_trailing_newline_preserved(self) -> None:
        """If the source ends without \\n, neither should the output."""
        assert not convert_md_links_to_wikilinks("[a](b.md)").endswith("\n")

    def test_empty_string_passes_through(self) -> None:
        assert convert_md_links_to_wikilinks("") == ""


class TestMakeWikiFooter:
    def test_includes_home_and_index_links(self) -> None:
        f = make_wiki_footer(project_name="LV_DCP", module_short=None)
        assert "[[Projects/LV_DCP/Home|Project home]]" in f
        assert "[[Projects/LV_DCP/Wiki/INDEX|Wiki index]]" in f

    def test_includes_modules_link_when_short_provided(self) -> None:
        f = make_wiki_footer(project_name="LV_DCP", module_short="apps")
        assert "[[Projects/LV_DCP/Modules/apps|Module stats: apps]]" in f

    def test_omits_modules_link_when_short_is_none(self) -> None:
        """For root-level articles like README, a stats link doesn't fit."""
        f = make_wiki_footer(project_name="LV_DCP", module_short=None)
        assert "Modules/" not in f

    def test_starts_with_separator(self) -> None:
        """The footer must visually separate from the article body."""
        f = make_wiki_footer(project_name="P", module_short=None)
        assert f.startswith("\n---")


class TestMakeIndexHeader:
    def test_links_to_home_modules_recent_changes(self) -> None:
        h = make_index_header(project_name="LV_DCP")
        assert "[[Projects/LV_DCP/Home|Project home]]" in h
        assert "[[Projects/LV_DCP/Modules|Modules]]" in h
        assert "[[Projects/LV_DCP/Recent Changes|Recent changes]]" in h

    def test_starts_with_blockquote(self) -> None:
        """The header is a one-line nav blockquote so it doesn't bury the H1."""
        assert make_index_header(project_name="P").startswith(">")
