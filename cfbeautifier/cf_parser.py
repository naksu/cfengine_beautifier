#!/usr/bin/env python

from __future__ import print_function
from __future__ import unicode_literals
import cf_beautifier as beautifier
import cf_lexer as lexer
import cf_structure as structure
import ply.yacc as yacc
import re
import sys

if sys.version_info[0] < 3:
    text_class = unicode
else:
    text_class = str

tokens = lexer.tokens

# This must be first by line number, and cannot be declared in grammar variable below, since all
# the functions in "grammar" share the same line number, and their order is unpredicatable
def p_specification(p):
    "specification : blocks_node"
    p[0] = p[1]

def declare_grammar():
    # return a convert_fn that returns the nth element from the parsed elements
    def nth(index):
        def fn(position, *elements):
            return elements[index]
        fn.__name__ = str("nth(%d)" % index) # str for Python 2
        return fn

    # convert_fn that returns the first parsed element
    first = nth(0)

    # convert_fn that just returns an empty list
    def empty_list(position, *elements):
        return []

    def modified(**kwargs):
        def fn(position, element):
            for key, value in kwargs.items():
                setattr(element, key, value)
            return element
        fn.__name__ = str("_".join(kwargs.keys())) # str for Python 2
        return fn

    parent_gets_comments = modified(priority_of_giving_parent_comments = 1)
    keeps_comments = modified(priority_of_giving_parent_comments = 0)

    def priority_comments(priority, convert_fn):
        """
        return a convert function that calls the given convert_fn and sets
        the priority_of_giving_parent_comments on the returned element.
        Returned function takes one element (and position) as argument.
        """
        def wrapper(position, element):
            element = convert_fn(position, element)
            element.priority_of_giving_parent_comments = priority
            return element
        wrapper.__name__ = str(convert_fn.__name__ + ("_priority_%d" % priority)) # str for Python 2
        return wrapper

    # convert_fn to return None
    def none(*args): None

    def line_broken_list(position, open_brace, items, *rest):
        # Difficult to do this via the grammar since both ArgumentList and List contain litems,
        # but ArgumentList items should not respect empty lines
        for item in items:
            item.respects_preceding_empty_line = True
        return structure.List(position, open_brace, items, *rest)

    def list_of(name, list_class,
                open = "none", close = "none", comma_separated = False, empty = False):
        format_args = { "plural" : name + "s",
                        "name" : name,
                        "open" : open,
                        "close" : close }

        if comma_separated:
            def append(position, head, comma, last):
                head.append(last)
                return head
            format_args["comma"] = "COMMA "
        else:
            def append(position, head, last):
                head.append(last)
                return head
            format_args["comma"] = ""

        def as_list(position, element):
            return [element]

        accumulator = [["{name}s : {name}", as_list],
                       ["{name}s : {name}s {comma}{name}", append]]
        if empty:
            accumulator.append(["{name}s : ", empty_list])

        constructor = [["{plural}_node : {open} {plural} none {close}", list_class]]

        return list(map(lambda statement_and_convert_fn:
                            [statement_and_convert_fn[0].format(**format_args),
                             statement_and_convert_fn[1]],
                        accumulator + constructor))

    # Argument order in structure classes' constructors must be such that they can be used as convert_fn
    grammar = (
        list_of("block", structure.Specification, empty = True) +
       [["""block : bundle
                  | body""", first]] +

        list_of("aitem", structure.ArgumentList,
                open = "open_paren", close = "close_paren", comma_separated = True, empty = True) +
        # The nones must match to what is in list_of function
       [["aitems_node : none empty none none", structure.ArgumentList],
        ["aitem : id", keeps_comments],

        ["bundle : bundle_token id id aitems_node bundle_statements_node", structure.Bundle]] +
        list_of("bundle_statement", structure.PromiseTypeList,
                open = "open_brace", close = "close_brace", empty = True) +
      [["bundle_statement : promise_type classpromises_node", structure.PromiseType],
        ["promise_type : PROMISE_TYPE", structure.String]] +
        list_of("classpromise", structure.ClassPromiseList, empty = True) +
       [["""classpromise : class
                         | promise_line""", first],
        ["""promise_line : promiser_statement
                         | promisee_statement""", first],
        # maybe_comma is not part of the syntax, but was found in CFEngine 3.6rc1 configs,
        # and is accepted by CFEngine
        ["promiser_statement : string none none maybe_comma constraints_node semicolon",
         structure.Promise],
        ["promisee_statement : string arrow rval maybe_comma constraints_node semicolon",
         structure.Promise]] +
        list_of("constraint", structure.ConstraintList, empty = True) +
       [["constraint : constraint_id assign rval maybe_comma", structure.Constraint],
        ["constraint_id : id", parent_gets_comments],

       ["body : body_token id id aitems_node bodyattribs_node", structure.Body]] +
        list_of("bodyattrib", structure.ClassSelectionList,
                open = "open_brace", close = "close_brace") +
       [["""bodyattrib : class
                       | selection semicolon""", first],
        ["selection : constraint_id assign rval maybe_comma", structure.Selection],

        ["class : class_expression", structure.Class],
        ["""rval : id
                 | symbol
                 | string
                 | list
                 | usefunction
                 | nakedvar""", parent_gets_comments],

        ["list : open_brace litems maybe_comma close_brace", line_broken_list],
        ["""litem : id
                  | string
                  | symbol
                  | nakedvar
                  | usefunction""", keeps_comments]] +
        list_of("litem", structure.ArgumentList,
                open = "open_paren", close = "close_paren", comma_separated = True, empty = True) +

       [["""maybe_comma : none
                        | comma""", first],
        ["""semicolon : SEMICOLON
          close_brace : CLOSE_BRACE
          close_paren : CLOSE_PAREN""", priority_comments(2, structure.String)],
        ["""       comma : COMMA
                  string : QSTRING
                nakedvar : NAKEDVAR
              open_brace : OPEN_BRACE
              open_paren : OPEN_PAREN
        class_expression : CLASS
            bundle_token : BUNDLE
              body_token : BODY
                  assign : ASSIGN
                  symbol : SYMBOL
                   arrow : ARROW
                      id : IDSYNTAX""", priority_comments(1, structure.String)],

        ["usefunction : functionid litems_node", structure.Function],
        ["""functionid : id
                       | symbol
                       | nakedvar""", first],

        ["none : ", none],
        ["empty :", empty_list]])

    # Declares a function (names p_...) as required by PLY. Expression is the grammar expression
    # (docstring in ply p_ function). The generated function calls convert_fn with Position
    # of the first element and all the matched elements as argument. convert_fn must return
    # the projection (normally, by using the given elements).
    def declare_grammar_function(expression, convert_fn):
        # Add p_ prefix and clean up characters that are invalid in a function
        function_name = "p_%s" % re.sub(r"[:| \n]+", "_", expression)
        def fn(p):
            p_size = len(p)
            if 1 < p_size:
                end_index = p_size - 1
                last = p[end_index]
                # Any other element must end where the last string ended
                # This is a workaround for PLY in some cases extending the covered space
                # until the next encountered element. -> Use last_end_of and last_end_line_number
                # from lexer for other elements.
                if isinstance(last, text_class):
                    # Only encountering a matched string may change the position
                    lexer.last_end_pos = p.lexpos(end_index) + len(last)
                    # The string may contain line breaks
                    lexer.last_end_line_number = p.linespan(end_index)[1] + last.count("\n")

                position = structure.Position(start_line_number = p.lineno(1),
                                              end_line_number = lexer.last_end_line_number,
                                              start_pos = p.lexpos(1),
                                              end_pos = lexer.last_end_pos,
                                              parse_index = lexer.parse_index)
            else:
                position = None
            # The elements will still need to be sorted to the order in which they were encountered,
            # in order to assign comments to the right node
            lexer.parse_index += 1

            p[0] = convert_fn(position, *p[1:])

        fn.__doc__ = expression
        fn.__name__ = str(function_name) # str for Python 2
        setattr(sys.modules[__name__], function_name, fn)

    for line in grammar:
        declare_grammar_function(*line)

declare_grammar()

def previous_end_of_line_pos(string, lexpos):
    "Return -1 if at the beginning of string"
    return string.rfind('\n', 0, lexpos)

def p_error(p):
    raise beautifier.ParserError(p.value, p.lineno, p.lexer.lexdata, p.lexpos)

yacc.yacc(debug = False)

######

def specification_from_string(string, options):
    def comments(comment_tokens, empty_line_numbers, last_line_number):
        def is_at_end_of_line(token, previous_eol_pos):
            # max, since if at beginning of doc, previous_eol_pos is -1, and the substring would
            # be empty, and not the actual substring from start of doc until the token
            return not not re.search(r"[^\t \n]", string[max(previous_eol_pos, 0):token.lexpos])
        def position(token):
            return structure.Position(start_line_number = token.lineno,
                                      end_line_number = token.lineno,
                                      start_pos = token.lexpos,
                                      end_pos = token.lexpos + len(token.value))

        class State(object):
            "Contains state of comment parsing"
            def __init__(self):
                self.comments = []
                self.current_comment = []
            def add_comment(self, comment):
                if self.current_comment:
                    if not self.current_comment.type:
                        if (self.current_comment.position.end_line_number + 1 in empty_line_numbers
                              or self.current_comment.position.end_line_number == last_line_number):
                            # This comment is not related to a node (if it is found in a List of
                            # some kind)
                            self.current_comment.type = "standalone"
                        else:
                            # This comment probably describes the next Node
                            self.current_comment.type = "next-node"
                    self.comments.insert(0, self.current_comment)
                self.current_comment = comment
            def commit_comment(self):
                self.add_comment(None)
            def is_part_of_current_comment(self, line_number):
                return(self.current_comment and
                       self.current_comment.position.start_line_number - 1 == line_number)

        state = State()

        for token in reversed(comment_tokens):
            previous_eol_pos = previous_end_of_line_pos(string, token.lexpos)
            # The original indentation is used to figure out whether standalone comments belong to
            # promise type list or class promise list
            original_indentation = token.lexpos - previous_eol_pos - 1
            if is_at_end_of_line(token, previous_eol_pos):
                state.add_comment(structure.Comment(position(token), token.value,
                                                    original_indentation,
                                                    type = "end-of-line"))
                state.commit_comment() # Don't add lines to end-of-line comment
            elif state.is_part_of_current_comment(token.lineno):
                state.current_comment.prepend_line(position(token), token.value)
            else:
                state.add_comment(structure.Comment(position(token), token.value,
                                                    original_indentation))
        state.commit_comment()
        return state.comments

    def line_numbers_of_empty_lines(string):
        return [index + 1
                for index, line in enumerate(string.split("\n"))
                if re.match(r"^[ \t\r]*$", line)]

    def set_empty_lines(nodes, empty_line_numbers):
        def line_number_to_node_map():
            node_by_line_number = {}
            last_line_number = -1
            for node in nodes:
                node_line_number = node.start_line_number_with_comment()
                if last_line_number != node_line_number:
                    node_by_line_number[node_line_number] = node
                    last_line_number = node_line_number
            return node_by_line_number

        node_by_line_number = line_number_to_node_map()
        for line_number in empty_line_numbers:
            node = node_by_line_number.get(line_number + 1)
            if node:
                node.preceded_by_empty_line = True

    cf_lexer = lexer.lexer()
    lexer.last_end_pos = 0
    lexer.last_end_line_number = 0
    lexer.parse_index = 0
    cf_lexer.input(string)

    specification = yacc.parse(string, lexer = cf_lexer, tracking = True)
    nodes = specification.descendants()
    empty_line_numbers = line_numbers_of_empty_lines(string)
    comments = comments(cf_lexer.comments, empty_line_numbers, cf_lexer.lineno)
    specification.add_comments(comments, [])
    set_empty_lines(comments, empty_line_numbers)
    set_empty_lines(nodes, empty_line_numbers)
    for node in nodes:
        node.after_parse(options)

    return specification
