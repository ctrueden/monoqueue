#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_parse.py
# ------------------------------------------------------------------------

import unittest

from monoqueue import parse


class TestParse(unittest.TestCase):

    data = {
        "greetings": {"aloha", "hello", "salutations", "felicitations"},
        "farewells": {"goodbye", "ciao", "see ya", "aloha"},
        "people": [
            {
                "name": "Goofus",
                "age": 13
            },
            {
                "name": "Gallant",
                "age": 14
            },
        ],
        "outer": {
            "inner": {
                "innermost": 44
            }
        }
    }

    #def test_any(self):
    #    self.assertTrue(parse.evaluate("any(greeting in farewells for greeting in greetings)", self.data))
    #    self.assertTrue(parse.evaluate("any(name == 'Gallant' for name in people/name)", self.data))
    #    self.assertFalse(parse.evaluate("any(name == 'Chuckles' for name in people/name)", self.data))

    #def test_all(self):
    #    self.assertTrue(parse.evaluate("all(age < 15 for age in people/age)", self.data))
    #    self.assertFalse(parse.evaluate("all(age > 13 for age in people/age)", self.data))

    def test_binary_op(self):
        self.assertEqual(["Goofus", "Gallant", 13, 14], parse.evaluate("people/name + people/age", self.data))
        self.assertEqual({"goodbye", "ciao", "see ya"}, parse.evaluate("farewells - greetings", self.data))
        self.assertEqual({"aloha"}, parse.evaluate("greetings & farewells", self.data))

    def test_inclusion(self):
        self.assertTrue(parse.evaluate("'Gallant' in people/name", self.data))
        self.assertFalse(parse.evaluate("'Gallant' in people/age", self.data))

    def test_boolean_ops(self):
        self.assertTrue(parse.evaluate("True or False", self.data))
        self.assertFalse(parse.evaluate("True and False", self.data))
        self.assertTrue(parse.evaluate("False or True or False", self.data))
        self.assertFalse(parse.evaluate("True and True and False", self.data))
        self.assertTrue(parse.evaluate("True or False and False", self.data)) # True or (False and False) -> True or False
        self.assertFalse(parse.evaluate("True and False or False", self.data)) # (True and False) or False -> False or False


    def test_slash_access(self):
        self.assertEqual(44, parse.evaluate("outer/inner/innermost", self.data))
        self.assertEqual(["Goofus", "Gallant"], parse.evaluate("people/name", self.data))


if __name__ == '__main__':
    unittest.main()
