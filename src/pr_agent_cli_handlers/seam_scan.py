"""Read PR-Agent's source and report drift from the activation table.

Run ``python -m pr_agent_cli_handlers.seam_scan [PR_AGENT_PACKAGE_DIR]``. Exit 1 when PR-Agent gained or
lost an ``ai_handler`` default of LiteLLMAIHandler, or a direct ``LiteLLMAIHandler()`` call.
"""
import ast
import sys
from pathlib import Path
from typing import Optional

from pr_agent_cli_handlers.activation import DIRECT_CONSTRUCTIONS, SEAMS


def _has_litellm_default(args: ast.arguments) -> bool:
    positional = args.posonlyargs + args.args
    pairs = list(zip(positional[len(positional) - len(args.defaults):], args.defaults, strict=True))
    pairs += [(arg, default) for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
              if default is not None]
    return any(arg.arg == "ai_handler" and isinstance(default, ast.Name) and default.id == "LiteLLMAIHandler"
               for arg, default in pairs)


def scan(package_dir: Path) -> tuple[set[tuple[str, str]], set[str]]:
    """Return the (module, class) pairs whose __init__ defaults ai_handler to LiteLLMAIHandler, and the
    package-relative files that call LiteLLMAIHandler() directly."""
    defaults: set[tuple[str, str]] = set()
    direct: set[str] = set()
    root = package_dir.parent
    for path in sorted(package_dir.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        module = relative[: -len(".py")].replace("/", ".").removesuffix(".__init__")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__"
                            and _has_litellm_default(item.args)):
                        defaults.add((module, node.name))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "LiteLLMAIHandler":
                direct.add(relative)
    return defaults, direct


def drift(package_dir: Path) -> list[str]:
    """Return one message per difference between ``package_dir`` and the activation table."""
    defaults, direct = scan(package_dir)
    expected_defaults = {(seam.module, seam.qualname) for seam in SEAMS}
    expected_direct = set(DIRECT_CONSTRUCTIONS)
    messages = [f"new seam not handled: {m}.{c}.__init__" for m, c in sorted(defaults - expected_defaults)]
    messages += [f"seam gone: {m}.{c}.__init__" for m, c in sorted(expected_defaults - defaults)]
    messages += [f"new direct LiteLLMAIHandler() call: {f}" for f in sorted(direct - expected_direct)]
    messages += [f"direct LiteLLMAIHandler() call gone: {f}" for f in sorted(expected_direct - direct)]
    return messages


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        package_dir = Path(args[0])
    else:
        import pr_agent

        package_dir = Path(pr_agent.__file__).parent
    messages = drift(package_dir)
    for message in messages:
        print(message)
    return 1 if messages else 0


if __name__ == "__main__":
    sys.exit(main())
