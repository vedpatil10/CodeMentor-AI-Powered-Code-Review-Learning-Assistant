from app.github.diff import parse_unified_diff
from app.retrieval.lexical import RetrievalPolicy, retrieve_python_symbols


def test_retriever_finds_referenced_definition_with_provenance() -> None:
    changed_diff = parse_unified_diff(
        "app/handler.py",
        "@@ -1 +1 @@\n-old = None\n+result = fetch_records()",
    )
    repository_files = {
        "app/store.py": "def fetch_records():\n    return []\n",
        "tests/test_store.py": "def test_fetch_records():\n    assert True\n",
        "README.md": "fetch_records is documented here",
    }

    result = retrieve_python_symbols(changed_diff, repository_files)

    assert result.identifiers == ["fetch_records", "result"]
    assert len(result.symbols) == 1
    assert result.symbols[0].qualified_name == "fetch_records"
    assert result.symbols[0].provenance == "app/store.py:1-2"
    assert result.total_bytes == len("def fetch_records():\n    return []")


def test_retriever_skips_unsafe_and_oversized_repository_files() -> None:
    changed_diff = parse_unified_diff("app/handler.py", "@@ -0,0 +1 @@\n+dangerous_call()")
    repository_files = {
        "../outside.py": "def dangerous_call():\n    pass",
        "app/large.py": "x" * 100,
        "app/target.py": "def dangerous_call():\n    pass",
    }

    result = retrieve_python_symbols(
        changed_diff,
        repository_files,
        RetrievalPolicy(max_file_bytes=50),
    )

    assert [symbol.path for symbol in result.symbols] == ["app/target.py"]
    assert result.skipped_paths == ["../outside.py", "app/large.py"]


def test_retriever_enforces_result_and_total_context_budgets() -> None:
    changed_diff = parse_unified_diff(
        "app/handler.py",
        "@@ -0,0 +1,2 @@\n+fetch_records()\n+other_fetch()",
    )
    repository_files = {
        "app/a.py": "def fetch_records():\n    return []",
        "app/b.py": "def other_fetch():\n    return []",
    }

    result = retrieve_python_symbols(
        changed_diff,
        repository_files,
        RetrievalPolicy(max_results=1, max_total_bytes=100),
    )

    assert len(result.symbols) == 1
    assert result.skipped_paths == ["app/b.py"]