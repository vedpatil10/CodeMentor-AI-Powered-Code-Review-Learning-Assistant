"""Extract Python symbols without importing or executing repository code."""

import ast
from dataclasses import dataclass
from enum import StrEnum


class SymbolKind(StrEnum):
    CLASS = "class"
    FUNCTION = "function"


@dataclass(frozen=True, slots=True)
class PythonSymbol:
    path: str
    name: str
    qualified_name: str
    kind: SymbolKind
    start_line: int
    end_line: int
    source: str


def extract_python_symbols(path: str, source: str) -> tuple[PythonSymbol, ...]:
    """Return class and function definitions from source text, without execution."""
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError, RecursionError):
        return ()

    source_lines = source.splitlines()
    symbols: list[PythonSymbol] = []

    class SymbolVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._record(node, SymbolKind.CLASS)
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._record(node, SymbolKind.FUNCTION)
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._record(node, SymbolKind.FUNCTION)
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def _record(self, node: ast.AST, kind: SymbolKind) -> None:
            name = getattr(node, "name")
            start_line = min(
                [node.lineno]
                + [decorator.lineno for decorator in getattr(node, "decorator_list", [])]
            )
            end_line = getattr(node, "end_lineno", node.lineno)
            qualified_name = ".".join([*self.scope, name])
            symbols.append(
                PythonSymbol(
                    path=path,
                    name=name,
                    qualified_name=qualified_name,
                    kind=kind,
                    start_line=start_line,
                    end_line=end_line,
                    source="\n".join(source_lines[start_line - 1 : end_line]),
                )
            )

    SymbolVisitor().visit(tree)
    return tuple(symbols)