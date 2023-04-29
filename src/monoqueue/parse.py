#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# parse.py
# ------------------------------------------------------------------------

"""
A custom parser for rule expressions, to avoid using the eval command.

This little parser enables our own mini-DSL, which has a conveniently succinct
data-structure delving mechanism with the divide (/) operator. For example:

    issue/assignee/login in issue/assignees/login

Is False for the given action item data:

    {
        "issue": {
            "url": "https://github.com/myorg/myrepo/issue/1",
            "assignee": {
                "id": 123,
                "login": "capone",
                "url": "https://api.github.com/users/capone"
            },
            "assignees": [
                {
                    "id": 456,
                    "login": "bonnie",
                    "url": "https://api.github.com/users/bonnie"
                },
                {
                    "id": 789,
                    "login": "clyde",
                    "url": "https://api.github.com/users/clyde"
                },
            ]
        }
    }

Because the expression evaluation leads to:

    "capone" in ["bonnie", "clyde"]

Other unary and binary operators, as well as regular Python constants,
are available, but arbitrary function calls are notably *not* possible.
"""

import ast

from functools import cache
from typing import Any


def dictlike(data: Any) -> bool:
    return hasattr(data, "get")


def listlike(data: Any) -> bool:
    # Meh, iterable is close enough. ;-)
    return hasattr(data, "__iter__")


def diggable(data: Any):
    return dictlike(data) or listlike(data)


@cache
def tree(expr: str):
    return ast.parse(expr, mode="eval").body


def unary(data: Any, expr: str, operand: ast.AST, op: ast.UnaryOp):
    value = evaluate(expr, data, operand)
    if isinstance(op, ast.Invert): return ~value
    if isinstance(op, ast.Not): return not value
    if isinstance(op, ast.UAdd): return +value
    if isinstance(op, ast.USub): return -value


def binary(expr: str, data: Any, lvalue: Any, op: ast.BinOp, right: ast.AST):
    if isinstance(op, ast.Div) and diggable(lvalue) and isinstance(right, ast.Name):
        # NB: Right-side of div operation digs into left-side data structure.
        # E.g. issue/assignees means data['issue']['assignees']
        # because data is a dict, and data['issue'] is also a dict.
        return evaluate(expr, lvalue, right)

    # Other operations evaluate normally (i.e. compute both halves first).
    rvalue = evaluate(expr, data, right)

    none = lvalue is None or rvalue is None

    # Evaluate binary ops (ast.operator) normally.
    if isinstance(op, ast.Add): return None if none else (lvalue + rvalue)
    if isinstance(op, ast.Sub): return None if none else (lvalue - rvalue)
    if isinstance(op, ast.Mult): return None if none else (lvalue * rvalue)
    if isinstance(op, ast.MatMult): return None if none else (lvalue @ rvalue)
    if isinstance(op, ast.Div): return None if none else (lvalue / rvalue)
    if isinstance(op, ast.Mod): return None if none else (lvalue % rvalue)
    if isinstance(op, ast.Pow): return None if none else (lvalue ** rvalue)
    if isinstance(op, ast.LShift): return None if none else (lvalue << rvalue)
    if isinstance(op, ast.RShift): return None if none else (lvalue >> rvalue)
    if isinstance(op, ast.BitOr): return None if none else (lvalue | rvalue)
    if isinstance(op, ast.BitXor): return None if none else (lvalue ^ rvalue)
    if isinstance(op, ast.BitAnd): return None if none else (lvalue & rvalue)
    if isinstance(op, ast.FloorDiv): return None if none else (lvalue // rvalue)

    # Evaluate comparison ops (ast.cmpop) normally.
    if isinstance(op, ast.Eq): return lvalue == rvalue
    if isinstance(op, ast.NotEq): return lvalue != rvalue
    if isinstance(op, ast.Lt): return False if none else (lvalue < rvalue)
    if isinstance(op, ast.LtE): return False if none else (lvalue <= rvalue)
    if isinstance(op, ast.Gt): return False if none else (lvalue > rvalue)
    if isinstance(op, ast.GtE): return False if none else (lvalue >= rvalue)
    if isinstance(op, ast.Is): return lvalue is rvalue
    if isinstance(op, ast.IsNot): return lvalue is not rvalue
    if isinstance(op, ast.In): return False if rvalue is None else (lvalue in rvalue)
    if isinstance(op, ast.NotIn): return True if rvalue is None else (lvalue not in rvalue)

    # Evaluate boolean ops (ast.boolop) normally.
    if isinstance(op, ast.And): return lvalue and rvalue
    if isinstance(op, ast.Or): return lvalue or rvalue

    raise ValueError(f"Unsupported operation: {type(op)}")


def evaluate(expr: str, data: Any, node: Any = None):
    if node is None:
        return evaluate(expr, data, tree(expr))

    if not isinstance(node, ast.AST):
        return node

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Tuple):
        return (evaluate(expr, data, elt) for elt in node.elts)

    if isinstance(node, ast.List):
        return [evaluate(expr, data, elt) for elt in node.elts]

    if isinstance(node, ast.Set):
        return {evaluate(expr, data, elt) for elt in node.elts}

    if isinstance(node, ast.Dict):
        return {
            evaluate(expr, data, k): evaluate(expr, data, v)
            for k, v in zip(node.keys, node.values)
        }

    if isinstance(node, ast.IfExp):
        return (
            evaluate(expr, data, node.body)
            if evaluate(expr, data, node.test)
            else evaluate(expr, data, node.orelse)
        )

    if isinstance(node, ast.Compare):
        value = evaluate(expr, data, node.left)
        for op, cmp in zip(node.ops, node.comparators):
            if not (
                isinstance(op, ast.BinOp) or
                isinstance(op, ast.cmpop) or
                isinstance(op, ast.boolop)
            ):
                raise ValueError(f"Non-binary comparison op: {type(op)}")
            value = binary(expr, data, value, op, cmp)
        return value

    if isinstance(node, ast.BoolOp):
        # NB: No short-circuiting for now.
        lvalue = evaluate(expr, data, node.values[0])
        for value in node.values[1:]:
            lvalue = binary(expr, data, lvalue, node.op, value)
        return lvalue

    if isinstance(node, ast.Name):
        # Dig into the data for this name!
        # Used with the special / binary operator.
        if data is None:
            return None
        if dictlike(data):
            return data.get(node.id)
        if listlike(data):
            return [evaluate(expr, el, node) for el in data]
        raise ValueError(f"Weird data type: {type(data)}")

    if isinstance(node, ast.UnaryOp):
        return unary(data, expr, node.operand, node.op)

    if isinstance(node, ast.BinOp):
        lvalue = evaluate(expr, data, node.left)
        return binary(expr, data, lvalue, node.op, node.right)

    if isinstance(node, ast.Call):
        func = node.func.id
        #print(ast.dump(node, indent=4))
        #if func == "all":
        #    pass
        #if func == "any":
        #    pass
        raise TypeError(f"Unsupported function call: {func}")

    raise TypeError(f"Unsupported {type(node)} expression: {ast.get_source_segment(expr, node)}")


def main():
    expr = input("Enter expression: ")
    result = evaluate(expr, data=None)
    print(result)


if __name__ == "__main__":
    main()
