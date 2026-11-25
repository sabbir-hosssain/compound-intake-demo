"""S1.10 architecture test: the LLM modules can never reach intake.audit (CLAUDE.md invariant 1).

The checker builds the import graph of every module under ``src/intake`` (static AST scan,
relative imports resolved properly, literal dynamic imports included), then walks it from each
LLM module (``extract``, ``explain``, ``adapters/*``). Reaching ``intake.audit`` directly or
through any intermediate module (e.g. a helper that wraps a commit function) is a failure.

The same checker runs against synthetic packages written to ``tmp_path`` to show it fails on
each forbidden import form, and passes on clean code.
"""

import ast
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

FORBIDDEN = "intake.audit"
DYNAMIC_UNRESOLVED = "<unresolvable dynamic import>"
LLM_MODULES = ("intake.extract", "intake.explain")
LLM_PACKAGES = ("intake.adapters",)


# --- checker ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Module:
    name: str
    path: Path
    is_package: bool

    @property
    def package(self) -> str:
        """The package that relative imports are resolved against."""
        return self.name if self.is_package else self.name.rpartition(".")[0]


def discover(src_root: Path, top: str = "intake") -> dict[str, Module]:
    """Map dotted module name -> Module for every .py file under src_root/top."""
    modules: dict[str, Module] = {}
    for path in sorted((src_root / top).rglob("*.py")):
        parts = list(path.relative_to(src_root).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts = parts[:-1]
        name = ".".join(parts)
        modules[name] = Module(name, path, is_package)
    return modules


def resolve_relative(package: str, level: int, module: str | None) -> str:
    """Absolute name for ``from <level dots><module> import ...`` inside ``package``."""
    if level == 0:
        return module or ""
    parts = package.split(".") if package else []
    if level - 1 > len(parts):
        return DYNAMIC_UNRESOLVED  # beyond the top-level package; Python would raise
    base = parts[: len(parts) - (level - 1)]
    if module:
        base.append(module)
    return ".".join(base)


def _str_const(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _dynamic_targets(call: ast.Call, package: str) -> set[str]:
    """Modules named by importlib.import_module(...) or __import__(...)."""
    name = _call_name(call.func)
    if name not in {"import_module", "__import__"}:
        return set()
    target = _str_const(call.args[0]) if call.args else None
    if target is None:
        return {DYNAMIC_UNRESOLVED}
    kwargs = {kw.arg: kw.value for kw in call.keywords}
    if name == "import_module":
        if not target.startswith("."):
            return {target}
        pkg_node = call.args[1] if len(call.args) > 1 else kwargs.get("package")
        pkg = _str_const(pkg_node) if pkg_node is not None else None
        if pkg is None:
            return {DYNAMIC_UNRESOLVED}
        stripped = target.lstrip(".")
        return {resolve_relative(pkg, len(target) - len(stripped), stripped or None)}
    # __import__(name, globals, locals, fromlist, level)
    level_node = call.args[4] if len(call.args) > 4 else kwargs.get("level")
    level = level_node.value if isinstance(level_node, ast.Constant) and isinstance(level_node.value, int) else 0
    base = resolve_relative(package, level, target or None)
    found = {base}
    fromlist = call.args[3] if len(call.args) > 3 else kwargs.get("fromlist")
    if isinstance(fromlist, (ast.List, ast.Tuple)):
        for elt in fromlist.elts:
            item = _str_const(elt)
            found.add(f"{base}.{item}" if item is not None else DYNAMIC_UNRESOLVED)
    elif fromlist is not None and not (isinstance(fromlist, ast.Constant) and fromlist.value is None):
        found.add(DYNAMIC_UNRESOLVED)
    return found


def imports_of(module: Module) -> set[str]:
    """Every module name this file may import: static, relative and literal dynamic imports.

    ``from X import y`` yields both ``X`` and ``X.y`` because ``y`` may be a submodule.
    """
    tree = ast.parse(module.path.read_text(), filename=str(module.path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative(module.package, node.level, node.module)
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Call):
            found.update(_dynamic_targets(node, module.package))
    return found


def _with_parents(name: str) -> list[str]:
    """Importing a.b.c also executes a and a.b."""
    parts = name.split(".")
    return [".".join(parts[: i + 1]) for i in range(len(parts))]


def is_forbidden(name: str) -> bool:
    return name == DYNAMIC_UNRESOLVED or name == FORBIDDEN or name.startswith(FORBIDDEN + ".")


def build_graph(modules: dict[str, Module]) -> dict[str, set[str]]:
    """Edges to in-package modules, plus any forbidden target even if the file is missing."""
    graph: dict[str, set[str]] = {}
    for name, module in modules.items():
        edges: set[str] = set()
        for target in imports_of(module):
            if is_forbidden(target):
                edges.add(target)
                continue
            edges.update(p for p in _with_parents(target) if p in modules and p != name)
        graph[name] = edges
    return graph


def path_to_forbidden(graph: dict[str, set[str]], start: str) -> list[str] | None:
    """Shortest import chain from start to a forbidden module, or None."""
    queue: deque[list[str]] = deque([[start]])
    seen = {start}
    while queue:
        chain = queue.popleft()
        for nxt in sorted(graph.get(chain[-1], ())):
            if is_forbidden(nxt):
                return [*chain, nxt]
            if nxt not in seen:
                seen.add(nxt)
                queue.append([*chain, nxt])
    return None


def llm_modules(modules: dict[str, Module]) -> list[str]:
    names = [m for m in LLM_MODULES if m in modules]
    for pkg in LLM_PACKAGES:
        names += [m for m in modules if m == pkg or m.startswith(pkg + ".")]
    return sorted(set(names))


def violations(src_root: Path) -> dict[str, list[str]]:
    """LLM module -> import chain that reaches intake.audit."""
    modules = discover(src_root)
    graph = build_graph(modules)
    found: dict[str, list[str]] = {}
    for start in llm_modules(modules):
        chain = path_to_forbidden(graph, start)
        if chain:
            found[start] = chain
    return found


# --- the real repo ------------------------------------------------------------------------


def test_llm_modules_are_scanned() -> None:
    scanned = llm_modules(discover(SRC))
    assert "intake.adapters" in scanned
    assert "intake.adapters.anthropic_client" in scanned
    assert "intake.adapters.cassette" in scanned
    for name in LLM_MODULES:
        if (SRC / Path(*name.split("."))).with_suffix(".py").exists():
            assert name in scanned


def test_audit_module_exists_where_the_scan_expects_it() -> None:
    assert FORBIDDEN in discover(SRC), "intake.audit moved; update FORBIDDEN or the scan is vacuous"


def test_llm_modules_cannot_reach_audit() -> None:
    found = violations(SRC)
    assert not found, "invariant 1 broken: " + "; ".join(" -> ".join(c) for c in found.values())


def test_importing_llm_modules_does_not_load_audit() -> None:
    """Runtime cross-check in a fresh interpreter: importing the LLM modules never loads intake.audit."""
    names = llm_modules(discover(SRC))
    code = "import importlib, sys\n" + "".join(f"importlib.import_module({n!r})\n" for n in names)
    code += f"assert {FORBIDDEN!r} not in sys.modules, sorted(m for m in sys.modules if m.startswith('intake'))\n"
    result = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True, cwd=REPO)
    assert result.returncode == 0, result.stderr


# --- the checker fails on synthetic forbidden imports ------------------------------------------


def _make_pkg(root: Path, files: dict[str, str]) -> Path:
    """Write a synthetic ``intake`` package under root/src; return the src root."""
    src = root / "src"
    base = {
        "intake/__init__.py": "",
        "intake/audit.py": "def append(conn, record):\n    pass\n",
        "intake/models.py": "",
        "intake/adapters/__init__.py": "",
    }
    for rel, text in {**base, **files}.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return src


FORBIDDEN_CASES = {
    "absolute import": ("intake/extract.py", "import intake.audit\n"),
    "absolute import as": ("intake/explain.py", "import intake.audit as a\n"),
    "from package import": ("intake/extract.py", "from intake import models, audit\n"),
    "from module import commit fn": ("intake/extract.py", "from intake.audit import append\n"),
    "relative from package": ("intake/adapters/x.py", "from .. import audit\n"),
    "relative from module": ("intake/adapters/x.py", "from ..audit import append\n"),
    "relative sibling of extract": ("intake/extract.py", "from . import audit\n"),
    "relative module from extract": ("intake/extract.py", "from .audit import append as commit\n"),
    "import inside function": ("intake/explain.py", "def f():\n    from intake.audit import append\n"),
    "importlib.import_module": ("intake/adapters/x.py", "import importlib\nimportlib.import_module('intake.audit')\n"),
    "import_module relative": (
        "intake/adapters/x.py",
        "from importlib import import_module\nimport_module('..audit', package='intake.adapters')\n",
    ),
    "import_module non-literal": ("intake/adapters/x.py", "import importlib\nimportlib.import_module(NAME)\n"),
    "__import__ dotted": ("intake/adapters/x.py", "__import__('intake.audit')\n"),
    "__import__ fromlist": ("intake/adapters/x.py", "__import__('intake', fromlist=['audit'])\n"),
    "__import__ relative level": ("intake/adapters/x.py", "__import__('audit', globals(), None, [], 2)\n"),
    "nested adapter package": ("intake/adapters/sub/y.py", "from ... import audit\n"),
}


@pytest.mark.parametrize("case", sorted(FORBIDDEN_CASES))
def test_checker_flags_synthetic_forbidden_import(tmp_path: Path, case: str) -> None:
    rel, text = FORBIDDEN_CASES[case]
    extra = {"intake/adapters/sub/__init__.py": ""} if "/sub/" in rel else {}
    src = _make_pkg(tmp_path, {rel: text, **extra})
    found = violations(src)
    assert found, f"{case}: forbidden import not detected"
    assert all(is_forbidden(chain[-1]) for chain in found.values())


def test_checker_flags_transitive_import_via_commit_helper(tmp_path: Path) -> None:
    src = _make_pkg(
        tmp_path,
        {
            "intake/commit.py": "from .audit import append\n\ndef commit(conn, rec):\n    append(conn, rec)\n",
            "intake/extract.py": "from intake.commit import commit\n",
        },
    )
    assert violations(src) == {"intake.extract": ["intake.extract", "intake.commit", "intake.audit"]}


def test_checker_flags_audit_reached_through_package_init(tmp_path: Path) -> None:
    src = _make_pkg(
        tmp_path,
        {
            "intake/helpers/__init__.py": "from .. import audit\n",
            "intake/helpers/text.py": "",
            "intake/adapters/x.py": "from intake.helpers import text\n",
        },
    )
    assert violations(src)["intake.adapters.x"][-1] == FORBIDDEN


def test_checker_passes_clean_synthetic_package(tmp_path: Path) -> None:
    src = _make_pkg(
        tmp_path,
        {
            "intake/audit_notes.py": "",
            "intake/extract.py": "from intake import models\nfrom . import audit_notes\nfrom .adapters import x\n",
            "intake/explain.py": "import importlib\nimportlib.import_module('intake.models')\n",
            "intake/adapters/x.py": "from . import y\nfrom ..models import *\nimport json\n",
            "intake/adapters/y.py": "__import__('json')\n",
            "intake/cli.py": "from intake import audit, extract\n",  # non-LLM modules may use audit
        },
    )
    assert violations(src) == {}


@pytest.mark.parametrize(
    ("package", "level", "module", "expected"),
    [
        ("intake.adapters", 1, None, "intake.adapters"),
        ("intake.adapters", 2, None, "intake"),
        ("intake.adapters", 2, "audit", "intake.audit"),
        ("intake", 1, "audit", "intake.audit"),
        ("intake", 0, "intake.audit", "intake.audit"),
        ("intake", 3, "audit", DYNAMIC_UNRESOLVED),
    ],
)
def test_resolve_relative(package: str, level: int, module: str | None, expected: str) -> None:
    assert resolve_relative(package, level, module) == expected
