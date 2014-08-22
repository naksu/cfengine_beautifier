from __future__ import print_function
from __future__ import unicode_literals

# Enable loading of module from parent directory
import os, sys
parent_dir = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
sys.path.append(parent_dir)

import cf_beautifier as beautifier
from cf_color import Color
import random
import cf_structure as structure
from cf_structure import Line
import re
import time
import unittest

class TestStructureHelpers(unittest.TestCase):
    def assertEqualWithDiff(self, actual, expected, message):
        self.assertEqual(actual, expected,
                         "%s:\nexpected: %s\nactual    %s" % (message, expected, actual))

    def test_joined_lines(self):
        test_cases = [("Joins empty array", [[]], []),
                      ("Joins empty arrays", [[], []], []),
                      ("Joins one arg", [[Line("string", 1)]], [Line("string", 1)]),
                      ("Joins empty array with content",
                       [[], [Line("string", 1)]], [Line("string", 1)]),
                      ("Joins content with empty and more text",
                       [[Line("string", 1)], [], [Line(" more", 0)]],
                       [Line("string more", 1)]),
                      ("Joins multiple lines and only uses first depth",
                       [[Line("string", 1), Line("second line", 2)],
                        [Line(" more", 3), Line("third line", 4), Line("fourth line", 5)]],
                       [Line("string", 1),
                        Line("second line more", 2),
                        Line("third line", 4),
                        Line("fourth line", 5)]),
                     ]
        for (message, line_arrays, expected) in test_cases:
          self.assertEqualWithDiff(structure.joined_lines(*line_arrays), expected, message)

    def test_find_index(self):
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 3, [1, 2, 3, 4]),
                                 2, "Finds in middle of list")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 1, [1, 2, 3, 4]),
                                 0, "Finds first item")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 4, [1, 2, 3, 4]),
                                 3, "Finds last item")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == "no", [1, 2, 3, 4]),
                                 None, "Return None if not found")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == "no", [1, 2, 3, 4],
                                                      not_found = "a"),
                                 "a", "Usees not_found argument")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 2, [1, 2, 3, 4],
                                                      not_found = "a"),
                                 1, "Not found does nothing when item found")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 3, [3, 2, 3, 4],
                                                      not_found = "a", start_index = 1),
                                 2, "Respects start_index")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 3, [3, 2, 3, 4],
                                                      not_found = "a", start_index = 0),
                                 0, "Respects start_index, no off by one after")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 3, [3, 2, 3, 4],
                                                      not_found = "a", start_index = 2),
                                 2, "Respects start_index, no off by one before")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 3, [3, 2, 3, 4],
                                                      not_found = "a",
                                                      reverse = True),
                                 2, "Supports reverse argument")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 3, [3, 2, 3, 4],
                                                      not_found = "a",
                                                      start_index = 1,
                                                      reverse = True),
                                 0, "Supports reverse argument with start index")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 3, [3, 2, 3, 4],
                                                      not_found = "a",
                                                      start_index = 2,
                                                      reverse = True),
                                 2, "Supports reverse argument with start index, no off-by-one")
        self.assertEqualWithDiff(structure.find_index(lambda x: x == 1, [3, 2, 3, 4],
                                                      not_found = "a",
                                                      start_index = 2,
                                                      reverse = True),
                                 "a", "Supports not finding in reverse")

def string_from_file(path):
  if sys.version_info[0] < 3:
    with open(path, "r") as file:
        return file.read().decode('utf-8-sig')
  else:
    with open(path, "r", encoding = "utf-8-sig") as file:
        return file.read()

def cf_file_names():
    return [os.path.join("test_cfs", name)
            for name in os.listdir("test_cfs")
            if re.match(r"^((?!expected).)*$", name) and name.endswith(".cf")]

def randomly_whitespaced(spec_string, line_endings):
    "return the string with random trailing whitespace at the end of each line"
    def random_chars(chars, count):
        def random_char_or_none(ignored_arg):
            x = random.randint(0, len(chars) - 1)
            return chars[x]
        return "".join(map(random_char_or_none, range(count)))
    return (line_endings.join(map(lambda line: line + random_chars(["\t", " ", ""], 2),
                              spec_string.split(line_endings)))
              + random_chars(["\t", "", line_endings, ""], 3))

class TestEndToEnd(unittest.TestCase):
    def assertEqualLines(self, actual, expected, message):
        actual_lines = actual.split("\n")
        expected_lines = expected.split("\n")
        for index, (actual_line, expected_line) in enumerate(map(lambda actual, expected:
                                                                     (actual, expected),
                                                                 actual_lines, expected_lines)):
            self.assertEqual(actual_line, expected_line,
                             "%s: Different lines at %d\n+'%s'\n-'%s'\n\n+++ACTUAL\n%s\n\n---EXPECTED\n%s" %
                                 (message, index, actual_line, expected_line, actual, expected))

    def test_beautify(self):
        seed = int(time.time())
        print("Running test with random seed", seed)
        random.seed(seed)

        for cf_file_name in cf_file_names():
            print(Color.red(cf_file_name))
            expected_file_path = cf_file_name[0:-3] + "_expected.cf"
            if not os.path.isfile(expected_file_path):
              # There is no *_excepted.cf file. Assume cf_file_name is already formatted as expected
              expected_file_path = cf_file_name
            expected = string_from_file(expected_file_path)
            options = beautifier.Options()
            original_cf_string = string_from_file(cf_file_name)
            beautified = beautifier.beautified_string(original_cf_string,
                                                      options = options)
            # Beautification should match expected
            self.assertEqualLines(beautified, expected, cf_file_name)
            # Beautification should be convergent
            self.assertEqualLines(beautifier.beautified_string(beautified, options = options),
                                  beautified, cf_file_name + " not convergent")
            # Should ignore white space
            if not "multiline_strings" in cf_file_name:
              # Multiline strings may not be appended white space without changing their meaning
              self.assertEqualLines(beautifier.beautified_string(
                                      randomly_whitespaced(original_cf_string,
                                                            beautifier.line_endings(original_cf_string,
                                                                                    None)),
                                      options = options),
                                    expected, cf_file_name + " not convergent")

    def assertBeautifies(self, original, expected, options, message):
        beautified = beautifier.beautified_string(original,
                                                  options = options)
        self.assertEqualLines(beautified, expected, message)

    def test_erro(self):
        cf_string = """bundle agent foo {
  classes:
    "promise" slist => => "value";
}
"""
        try:
          beautifier.beautified_string(cf_string)
        except beautifier.ParserError as error:
          self.assertEqual("Syntax error, line 3, column 24: '=>'", str(error), "Is human readable")
          self.assertEqual(3, error.line_number, "Knows line number of the error")
          self.assertEqual(24, error.column, "Knows column of the error")
          self.assertEqual("=>", error.fragment, "Knows the text of the error")
          self.assertEqual(53, error.position, "Knows the lexpos of the error")
        else:
          self.fail("Did not raise except")

    def test_no_sort(self):
        options = beautifier.Options()
        options.sorts_promise_types_to_evaluation_order = False
        original = """bundle agent foo {
                        classes:
                          "promise";

                        vars:
                            "promise2";
                      }
                   """
        expected = """bundle agent foo {
  classes:
      "promise";

  vars:
      "promise2";
}
"""
        self.assertBeautifies(original, expected, options, "Supports not sorting")

    def test_no_removal_of_empty(self):
        options = beautifier.Options()
        options.removes_empty_promise_types = False
        original = """bundle agent foo {
                        vars:

                       classes:
                         "promise";
                     }
                   """
        expected = """bundle agent foo {
  vars:

  classes:
      "promise";
}
"""
        self.assertBeautifies(original, expected, options, "Supports non-removal of empty promises")
