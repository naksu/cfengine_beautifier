from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

def previous_end_of_line_pos(string, lexpos):
    "Return -1 if at the beginning of string"
    return string.rfind('\n', 0, lexpos)

class ParserError(Exception):
    def __init__(self, fragment, line_number, input_string, lexpos):
        def column(input, lexpos):
            return (lexpos - previous_end_of_line_pos(input, lexpos))
        self.line_number = line_number
        self.column = column(input_string, lexpos)
        self.position = lexpos
        self.fragment = fragment
        Exception.__init__(self,
                           "Syntax error, line %d, column %d: '%s'" % (line_number, self.column, fragment))
