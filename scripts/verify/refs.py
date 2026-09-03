"""The two things a large refactor breaks without raising until the code is walked into.

1. A module that will not parse, which is what a file truncated by a bad write looks like.
2. `self.something()` where nothing in the project defines `something` any more, which is
   what deleting a method and missing one of its callers leaves behind.

The second is deliberately approximate. `World` is one class spread over ten mixins, so
resolving an attribute properly would mean resolving the mixin graph; instead every name
defined or assigned anywhere in `src` counts as defined, and only a call to a name that
exists nowhere at all is reported. That trades every false positive away for the one real
case: a name that used to exist and now does not.

    uv run python scripts/verify/refs.py
"""

import argparse
import ast
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness


def parse_all(src: Path):
    trees, broken = {}, []
    for path in sorted(src.rglob("*.py")):
        text = path.read_text()
        try:
            trees[path] = ast.parse(text, filename=str(path))
        except SyntaxError as e:
            broken.append((path, f"line {e.lineno}: {e.msg}"))
    return trees, broken


def defined_names(trees):
    """Every name that could legitimately be behind a `self.x`: methods, class attributes,
    anything assigned to `self`, and the properties and slots that come with them."""
    names = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del):
                names.add(node.attr)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute):
                names.add(node.target.attr)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
    return names


def called_on_self(trees):
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self":
                yield path, node.lineno, func.attr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, default=harness.REPO / "src")
    args = parser.parse_args()

    trees, broken = parse_all(args.src)
    problems = [f"{path.relative_to(args.src)}: will not parse, {why}" for path, why in broken]

    known = defined_names(trees) | set(dir(object))
    for path, lineno, attr in called_on_self(trees):
        if attr not in known and not attr.startswith("__"):
            problems.append(f"{path.relative_to(args.src)}:{lineno}: self.{attr}() is defined nowhere in src")

    if problems:
        print(f"FAIL: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"OK: {len(trees)} modules parse, every self.x() call resolves")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
