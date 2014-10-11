from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import os

this_dir = os.path.realpath(os.path.dirname(os.path.realpath(__file__)))
beautifier_executable_path = os.path.join(this_dir, "cf-beautifier")
test_cf_dir = os.path.join(this_dir, "test_cfs")

from .. import beautifier
from ..color import Color
from ..version_abstraction import string_from_file
import random
from .. import structure
from ..structure import Line
from ..util import ParserError
import re
import shutil
import subprocess
import tempfile
import time
import unittest

temp_dir = os.path.join(tempfile.gettempdir(), "cfbeautifier_tmp")

def clear_temp_dir():
  try:
    shutil.rmtree(temp_dir)
  except OSError:
    pass
  os.makedirs(temp_dir)

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

def cf_file_names():
    return [os.path.join(test_cf_dir, name)
            for name in os.listdir(test_cf_dir)
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
        def numbered_lines(document):
            return ["%3d: %s" % (index, line) for index, line in enumerate(document.split("\n"))]
        actual_lines = numbered_lines(actual)
        expected_lines = numbered_lines(expected)
        for actual_line, expected_line in zip(actual_lines, expected_lines):
            self.assertEqual(actual_line, expected_line,
                             "+++ACTUAL\n%s\n\n---EXPECTED\n%s\n\n%s: Different lines\n+'%s'\n-'%s'" %
                                 ("\n".join(actual_lines), "\n".join(expected_lines),
                                  message, actual_line, expected_line))

    def _for_original_and_expected_in_each_cf_file(self, fn):
        """
        Calls fn for each cf test file
        fn must have signature (original, expected, cf_file_name) -> None
        """
        for cf_file_name in cf_file_names():
            print(Color.red(cf_file_name))
            expected_file_path = cf_file_name[0:-3] + "_expected.cf"
            if not os.path.isfile(expected_file_path):
              # There is no *_excepted.cf file. Assume cf_file_name is already formatted as expected
              expected_file_path = cf_file_name
            expected = string_from_file(expected_file_path)
            original_cf_string = string_from_file(cf_file_name)
            fn(original_cf_string, expected, cf_file_name)

    def test_beautify(self):
        seed = int(time.time())
        print("Running test with random seed", seed)
        random.seed(seed)

        def compare(original_cf_string, expected, cf_file_name):
            options = beautifier.Options()
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

        self._for_original_and_expected_in_each_cf_file(compare)

    def assertBeautifies(self, original, expected, options, message):
        beautified = beautifier.beautified_string(original,
                                                  options = options)
        self.assertEqualLines(beautified, expected, message)

    def test_error(self):
        cf_string = """bundle agent foo {
  classes:
    "promise" slist => => "value";
}
"""
        try:
          beautifier.beautified_string(cf_string)
        except ParserError as error:
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

    def test_command_line_interface_with_stdin(self):
        def compare(original_cf_string, expected, cf_file_name):
            beautified, err = beautified_via_cli([], original_cf_string)
            self.assertEqual(err, "")
            self.assertEqualLines(beautified, expected, cf_file_name)

        self._for_original_and_expected_in_each_cf_file(compare)

    def test_command_line_interface_with_output_file(self):
        clear_temp_dir()
        def compare(original_cf_string, expected, cf_file_name):
            output_path = os.path.join(temp_dir, "tmp.cf")
            for stream in beautified_via_cli(["--out", output_path, cf_file_name],
                                             original_cf_string):
              self.assertEqual(stream, "")
            self.assertEqualLines(string_from_file(output_path), expected, cf_file_name)

        self._for_original_and_expected_in_each_cf_file(compare)

def beautified_via_cli(args, input):
    process = subprocess.Popen(["./cf-beautify"] + args,
                               stdin = subprocess.PIPE,
                               stdout = subprocess.PIPE,
                               stderr = subprocess.PIPE)
    out, err = process.communicate(input.encode("utf-8"))
    out = out.decode('utf-8-sig')
    err = err.decode('utf-8-sig')
    return (out, err)

def main():
    unittest.main()

if __name__ == '__main__':
  main()