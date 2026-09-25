"""What a change breaks without raising until the code is walked into.

1. A module that will not parse, which is what a file truncated by a bad write looks like.
2. `self.something()` where nothing in the project defines `something` any more, which is
   what deleting a method and missing one of its callers leaves behind.
3. A background thread that changes a list or a dict nobody gave it. A worker changes the
   world through `core/mainthread.post` and nothing else; the bug hunts found that rule
   broken three times by reading, so it is read here instead. Every function a thread is
   started on is walked, with every call out of it that names one function in `src`, and
   any in-place change it makes (`.append`, `.clear`, `x[k] = v`, ...) is reported unless
   it is to something in `WORKER_OWNED`. A plain `obj.attr = value` is not reported: one
   reference swapped is not an iteration broken.

The second is deliberately approximate. `World` is one class spread over ten mixins, so
resolving an attribute properly would mean resolving the mixin graph; instead every name
defined or assigned anywhere in `src` counts as defined, and only a call to a name that
exists nowhere at all is reported. That trades every false positive away for the one real
case: a name that used to exist and now does not.

    uv run python scripts/verify/refs.py
"""

import argparse
import ast
import builtins
import sys
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


# What a worker may change in place, by attribute name: buffers only the worker fills and the
# main thread takes from, the queue's own bookkeeping, and the save, which holds its own
# lock. Adding a name here is a claim that nothing on the main thread iterates it.
WORKER_OWNED = {
    "ready_names",
    "used_names",
    "ready_taunts",
    "_pads",
    "tasks",
    "interactive_waiting",
    "_naming_villages",
    "_completing",
    "save_system",
}

MUTATORS = {"append", "extend", "insert", "remove", "pop", "popitem", "clear", "update", "add", "discard", "setdefault"}


def _mutations(fn):
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in MUTATORS:
            target = node.func.value
            if _held(target) and not _reaches(target, WORKER_OWNED):
                yield node.lineno, f"{ast.unparse(target)}.{node.func.attr}()"
        elif isinstance(node, ast.Assign | ast.AugAssign | ast.Delete):
            targets = node.targets if isinstance(node, ast.Assign | ast.Delete) else [node.target]
            for target in targets:
                owned = _reaches(target, WORKER_OWNED)
                if isinstance(target, ast.Subscript) and _held(target.value) and not owned:
                    yield node.lineno, f"{ast.unparse(target)} ="


def _held(node):
    """Whether this is reached through some object's attribute, rather than being a local the
    worker built itself and can do what it likes with."""
    while isinstance(node, ast.Subscript):
        node = node.value
    return isinstance(node, ast.Attribute)


def _reaches(node, names):
    while isinstance(node, ast.Attribute | ast.Subscript):
        if isinstance(node, ast.Attribute) and node.attr in names:
            return True
        node = node.value
    return False


def _callees(fn):
    """Calls out of `fn` that can be followed by name: `self.x()` and a bare `x()`, which are
    looked up in the same file first, and `obj.x()`, followed only when one function in all
    of `src` has that name. A container's own methods and the builtins are never followed,
    or `self.save_system.update()` would be read as a call to `World.update`."""
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id not in _BUILTINS:
            yield func.id, True
        elif isinstance(func, ast.Attribute) and func.attr not in MUTATORS | _BUILTINS | {"get"}:
            yield func.attr, isinstance(func.value, ast.Name) and func.value.id == "self"


_BUILTINS = set(dir(builtins))


def worker_writes(trees, depth=5):
    functions = {}
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.setdefault(node.name, []).append((path, node))

    def resolve(path, name, local=True):
        found = functions.get(name, [])
        here = [entry for entry in found if entry[0] == path] if local else []
        return here[0] if len(here) == 1 else (found[0] if len(found) == 1 else None)

    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and ast.unparse(node.func).endswith("Thread")):
                continue
            target = next((kw.value for kw in node.keywords if kw.arg == "target"), None)
            name = getattr(target, "attr", None) or getattr(target, "id", None)
            start = resolve(path, name) if name else None
            if start is None:
                continue
            seen, stack = set(), [(start, [name])]
            while stack:
                (where, fn), trail = stack.pop()
                if (where, fn.name) in seen:
                    continue
                seen.add((where, fn.name))
                for lineno, what in _mutations(fn):
                    yield path, node.lineno, " > ".join(trail), where, lineno, what
                if len(trail) < depth:
                    for callee, local in _callees(fn):
                        found = resolve(where, callee, local)
                        if found is not None:
                            stack.append((found, [*trail, callee]))


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

    for path, lineno, trail, where, at, what in worker_writes(trees):
        problems.append(
            f"{path.relative_to(args.src)}:{lineno}: a thread on {trail} changes {what} "
            f"({where.relative_to(args.src)}:{at}); post it through core.mainthread"
        )

    if problems:
        print(f"FAIL: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"OK: {len(trees)} modules parse, every self.x() call resolves, no worker changes the world")
    return 0


if __name__ == "__main__":
    sys.exit(main())
