#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# score.py
# ------------------------------------------------------------------------

"""
Scoring rule parser and evaluator.
"""

import ast

s = "'ctrueden' in issue/assignees/login"

expr = ast.parse(s, mode="eval")

print(ast.dump(expr))


#Expression(body=Compare(left=Constant(value='ctrueden'), ops=[In()], comparators=[BinOp(left=BinOp(left=Name(id='issue', ctx=Load()), op=Div(), right=Name(id='assignees', ctx=Load())), op=Div(), right=Name(id='login', ctx=Load()))]))



def evaluate(expr):
    if isinstance(expr.body, ast.Compare):
        pass
    elif isinstance(expr.body, 

