from app.retrieval.symbols import SymbolKind, extract_python_symbols


def test_extracts_nested_classes_functions_and_decorated_line_ranges() -> None:
    source = """def outer():
    @classmethod
    def inner(cls):
        return cls

class Repository:
    async def fetch_records(self):
        return []
"""

    symbols = extract_python_symbols("app/repository.py", source)

    assert [(symbol.qualified_name, symbol.kind) for symbol in symbols] == [
        ("outer", SymbolKind.FUNCTION),
        ("outer.inner", SymbolKind.FUNCTION),
        ("Repository", SymbolKind.CLASS),
        ("Repository.fetch_records", SymbolKind.FUNCTION),
    ]
    assert symbols[1].start_line == 2
    assert symbols[1].end_line == 4
    assert symbols[1].source.startswith("    @classmethod")


def test_symbol_parser_returns_no_results_for_invalid_python() -> None:
    assert extract_python_symbols("broken.py", "def missing(:\n    pass") == ()


def test_symbol_parser_does_not_execute_module_code() -> None:
    source = """raise RuntimeError('must not execute')
def safe_function():
    return True
"""

    symbols = extract_python_symbols("untrusted.py", source)

    assert [symbol.name for symbol in symbols] == ["safe_function"]