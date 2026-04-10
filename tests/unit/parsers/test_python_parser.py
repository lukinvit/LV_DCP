from libs.core.entities import RelationType, SymbolType
from libs.parsers.python import PythonParser

SOURCE = b'''
"""module docstring"""

from datetime import datetime
from app.models.user import User

CONSTANT = 42


class Service:
    """A service."""

    def run(self) -> None:
        helper()
        self.process()

    def process(self) -> None:
        pass


def helper() -> int:
    return 1
'''


def test_python_extracts_functions_and_classes() -> None:
    result = PythonParser().parse(file_path="app/svc.py", data=SOURCE)
    names = {s.name for s in result.symbols}
    assert "Service" in names
    assert "helper" in names
    assert "run" in names
    assert "process" in names
    assert "CONSTANT" in names


def test_python_records_imports_as_relations() -> None:
    result = PythonParser().parse(file_path="app/svc.py", data=SOURCE)
    imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
    targets = {r.dst_ref for r in imports}
    assert "datetime" in targets
    assert "app.models.user.User" in targets


def test_python_records_defines_relations() -> None:
    result = PythonParser().parse(file_path="app/svc.py", data=SOURCE)
    defines = [r for r in result.relations if r.relation_type == RelationType.DEFINES]
    dst_refs = {r.dst_ref for r in defines}
    assert any("Service" in x for x in dst_refs)
    assert any("helper" in x for x in dst_refs)


def test_python_records_same_file_calls() -> None:
    result = PythonParser().parse(file_path="app/svc.py", data=SOURCE)
    calls = [r for r in result.relations if r.relation_type == RelationType.SAME_FILE_CALLS]
    targets = {r.dst_ref for r in calls}
    assert any("helper" in t for t in targets)


def test_python_handles_syntax_error_gracefully() -> None:
    result = PythonParser().parse(file_path="bad.py", data=b"def (((")
    assert result.errors != ()


def test_python_symbol_types() -> None:
    result = PythonParser().parse(file_path="app/svc.py", data=SOURCE)
    by_name = {s.name: s for s in result.symbols}
    assert by_name["Service"].symbol_type == SymbolType.CLASS
    assert by_name["helper"].symbol_type == SymbolType.FUNCTION
    assert by_name["run"].symbol_type == SymbolType.METHOD
    assert by_name["CONSTANT"].symbol_type == SymbolType.CONSTANT
