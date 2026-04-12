from libs.parsers.text_parsers import (
    JsonParser,
    MarkdownParser,
    TomlParser,
    YamlParser,
)


def test_markdown_extracts_headings_as_symbols() -> None:
    parser = MarkdownParser()
    data = b"# Title\n\n## Section A\n\ntext\n\n## Section B\n"
    result = parser.parse(file_path="docs/a.md", data=data)
    names = [s.name for s in result.symbols]
    assert "Title" in names
    assert "Section A" in names
    assert "Section B" in names


def test_markdown_extracts_all_heading_levels() -> None:
    parser = MarkdownParser()
    data = b"# Introduction\n\nSome text\n\n## Architecture\n\n### Components\n"
    result = parser.parse(file_path="docs/design.md", data=data)
    assert len(result.symbols) == 3
    names = [s.name for s in result.symbols]
    assert "Introduction" in names
    assert "Architecture" in names
    assert "Components" in names


def test_markdown_role_is_docs() -> None:
    parser = MarkdownParser()
    result = parser.parse(file_path="README.md", data=b"# Hello\n")
    assert result.role == "docs"


def test_markdown_handles_empty_file() -> None:
    parser = MarkdownParser()
    result = parser.parse(file_path="docs/empty.md", data=b"")
    assert len(result.symbols) == 0


def test_markdown_line_numbers_are_correct() -> None:
    parser = MarkdownParser()
    data = b"# First\n\ntext\n\n## Second\n"
    result = parser.parse(file_path="docs/a.md", data=data)
    assert result.symbols[0].start_line == 1
    assert result.symbols[1].start_line == 5


def test_markdown_fq_name_contains_file_path() -> None:
    parser = MarkdownParser()
    data = b"# Heading\n"
    result = parser.parse(file_path="docs/readme.md", data=data)
    assert result.symbols[0].fq_name.startswith("docs/readme.md#")


def test_yaml_parses_valid_doc_without_symbols() -> None:
    parser = YamlParser()
    data = b"key: value\nlist:\n  - 1\n  - 2\n"
    result = parser.parse(file_path="config.yaml", data=data)
    assert result.language == "yaml"
    assert result.errors == ()


def test_yaml_records_error_on_invalid() -> None:
    parser = YamlParser()
    result = parser.parse(file_path="bad.yaml", data=b": : : bad")
    assert result.errors != ()


def test_json_parses_valid() -> None:
    parser = JsonParser()
    result = parser.parse(file_path="a.json", data=b'{"a":1}')
    assert result.errors == ()


def test_toml_parses_valid() -> None:
    parser = TomlParser()
    result = parser.parse(file_path="a.toml", data=b'key = "value"\n')
    assert result.errors == ()
