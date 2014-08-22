#!/usr/bin/env python

from __future__ import print_function
from __future__ import unicode_literals
import cf_parser as parser
import cf_structure as structure
import copy

class ParserError(Exception):
    def __init__(self, fragment, line_number, input_string, lexpos):
        def column(input, lexpos):
            return (lexpos - parser.previous_end_of_line_pos(input, lexpos))
        self.line_number = line_number
        self.column = column(input_string, lexpos)
        self.position = lexpos
        self.fragment = fragment
        Exception.__init__(self,
                           "Syntax error, line %d, column %d: '%s'" % (line_number, self.column, fragment))

class Options(object):
    def __init__(self):
        self.removes_empty_promise_types = True
        self.sorts_promise_types_to_evaluation_order = True
        self.page_width = 100
        self.line_endings = None

def line_endings(string, line_endings):
    if line_endings:
        return line_endings
    if "\r\n" in string:
        return "\r\n"
    return "\n"

def beautified_string(string, options = None):
    "Raises ParserError if fails to parse"
    options = copy.copy(options) or Options()
    options.line_endings = line_endings(string, options.line_endings)
    options = structure.Options(options)
    return parser.specification_from_string(string, options).to_string(options)
