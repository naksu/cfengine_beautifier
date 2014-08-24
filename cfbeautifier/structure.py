from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals
from functools import reduce
from itertools import chain
import copy
import re
import sys

TAB_SIZE = 2

class Position(object):
    def __init__(self, start_line_number, end_line_number, start_pos, end_pos, parse_index = None):
        self.start_line_number = start_line_number
        self.end_line_number = end_line_number
        self.start_pos = start_pos
        self.end_pos = end_pos
        self.parse_index = parse_index
    def covers(self, line_number):
        return self.start_line_number <= line_number <= self.end_line_number
    def __repr__(self):
        return "(%d..%d), (%d..%d)" % (self.start_line_number,
                                       self.end_line_number,
                                       self.start_pos,
                                       self.end_pos)

def isinstance_fn(klass):
    def fn(object):
        return isinstance(object, klass)
    fn.__name__ = str("isinstance_" + klass.__name__) # str for Python 2
    return fn

class Line(object):
    def __init__(self, string, indent = None, end_comments = []):
        self.string = string
        self.indent = indent
        self.end_comments = end_comments
    def length(self):
        # TODO need to find first line break in the string, but in a fast way. Could remember this perhaps
        # from parsing.
        return len(self.string) + (self.indent or 0)
    def joined(self, line):
        return Line(self.string + line.string,
                    indent = self.indent if self.indent != None else line.indent,
                    end_comments = self.end_comments + line.end_comments)
    def __eq__(self, line):
        return isinstance(line, self.__class__) and self.__dict__ == line.__dict__
    def __ne__(self, line):
        return not self.__eq__(line)

class Options(object):
    DEFAULT_RESPECTS_PRECEDING_EMPTY_LINE = None
    def __init__(self, beautifier_options):
        # Copy properties from beautifier_options
        for attr in filter(lambda attr: not attr.startswith("__"), dir(beautifier_options)):
            value = getattr(beautifier_options, attr)
            if not hasattr(value, '__call__'):
                setattr(self, attr, value)
        self.indent = 0
        self.ancestor_indent = 0
        # Whether there may be a line break in constraint (type => value) before value
        self.may_line_break_constraint = True
        # if True or False, overrides Node
        self.respects_preceding_empty_line = Options.DEFAULT_RESPECTS_PRECEDING_EMPTY_LINE
    def depth(self):
        return self.indent + self.ancestor_indent
    def tabs(self, count):
        return " " * (TAB_SIZE * count)
    def available_width(self):
        return self.page_width - self.depth()
    def indent_lines(self, lines):
        if lines:
            depth = self.indent
            for line in lines[1:]:
                line.indent = (line.indent or 0) + depth
    def child(self, *line_arrays_and_char_counts, **kwargs):
        # Cannot have explicit keyword args after splat args
        respects_preceding_empty_line = kwargs.get("respects_preceding_empty_line",
                                                   Options.DEFAULT_RESPECTS_PRECEDING_EMPTY_LINE)

        def added_depth():
            def depth(lines_or_char_count):
                if isinstance(lines_or_char_count, list):
                    return lines_or_char_count[-1].length()
                else:
                    return lines_or_char_count
            return sum(map(depth, line_arrays_and_char_counts))
        child = copy.copy(self)
        child.ancestor_indent += self.indent
        child.indent = added_depth()
        # Don't inherit the respect for empty line; it is used by list for inlining
        child.respects_preceding_empty_line = respects_preceding_empty_line
        return child

def joined_lines(*line_arrays):
    joined_lines = []
    for lines in line_arrays:
        if lines:
            if not joined_lines:
                joined_lines.extend(lines)
            else:
                joined_lines[-1] = joined_lines[-1].joined(lines[0])
                joined_lines.extend(lines[1:])
    return joined_lines

def line_lengths(lines):
    return map(lambda line: line.length(), lines)

def max_line_length(lines):
    return max(line_lengths(lines))

def partition(is_included_fn, items):
    """
    Return (included, excluded) pair, in which first element is a list for which is_included_fn
    evaluates trueness, and second element is a list for which is_included_fn evaluates falseness
    """
    item_by_exclusion = { True : [], False : [] }
    for item in items:
        # "not" to normalise all values to either True or False
        item_by_exclusion[not is_included_fn(item)].append(item)
    return (item_by_exclusion[False], item_by_exclusion[True])

def find_in_list(predicate, list):
    for item in list:
        if predicate(item):
            return item;

def find_index(predicate, items, start_index = None, not_found = None, reverse = False):
    if reverse:
        if start_index == None:
            start_index = len(items)
        index_item_pairs = reversed(list(enumerate(items))[:start_index + 1])
    else:
        if start_index == None:
            start_index = 0
        index_item_pairs = list(enumerate(items))[start_index:]

    for index, item in index_item_pairs:
        if predicate(item):
            return index
    return not_found

def add_comments_to_items(items, comments_by_item, parents):
    """
    Add to children in order. comments_by_item is not predictable order, therefore items list is
    taken as argument)
    """
    for item in items:
        comments = comments_by_item.get(item)
        if comments:
            item.add_comments(comments, parents)

def is_end_of_line_comment_for(node, comment, nodes):
    def last_for_line(line_number):
        i = len(nodes) - 1
        while 0 <= i:
            node_at_i = nodes[i]
            pos_at_i = node_at_i.position
            if pos_at_i.start_line_number <= line_number <= pos_at_i.end_line_number:
                return node_at_i
            if node_at_i == node:
                return None
            i -= 1
        return None
    return (comment.position.end_line_number <= node.position.end_line_number and
            last_for_line(comment.position.start_line_number) == node)

def items_and_comments_by_item(items, comments, standalone_policy,
                               is_standalone_comment_for_node_fn = None):
    """
    Return items interleaved with standalone comments, and item -> comments dictionary
    standalone_policy: if insert, standalone comments are inserted to the appropriate position in
                                  returned item list
                       if give_to_child, such comments are given to the next child element.
                                         In this case, the returned item list is equal to the
                                         item list given as parameter.
    is_standalone_comment_for_node_fn: called on standalone comments to check if the comment belongs
                                       to the item, even though it appears after the item.
                                       This allows assigning standalone comments to promise type from
                                       bundle level, based on original indentation.
                                       Only used if standalone policy is "insert"
    """
    new_items = []
    comments_by_item = {}
    item_index = 0
    for comment in comments:
        def is_standalone_comment_before(node):
            return (comment.is_standalone()
                    and comment.position.start_line_number < node.position.start_line_number)
        # reset in case the value in last round was a value in item -> comments dict
        list_onto_add = new_items
        item_count = len(items)
        while item_index < item_count:
            item = items[item_index]
            if (standalone_policy == "insert" and is_standalone_comment_before(item)):
                # This standalone comment should be inserted at this point in item list
                break

            def is_last_node_or_standalone_comment_is_before_next():
                return (item_count <= item_index + 1
                        or (comment.is_standalone()
                            and comment.position.start_line_number <
                               items[item_index + 1].position.start_line_number))

            if(comment.position.end_line_number < item.position.end_line_number
               or is_end_of_line_comment_for(item, comment, items)
               # This behavior is indented to allow non-removal of promise types that are otherwise
               # empty but have comments
               or (standalone_policy == "insert"
                   # The comment may not be a line comment (or any other comment) of a later node.
                   and is_last_node_or_standalone_comment_is_before_next()
                   # check if the client wants a standalone comment to be given to this node
                   and is_standalone_comment_for_node_fn(item, comment))):
                list_onto_add = comments_by_item[item] = comments_by_item.get(item, [])
                break
            new_items.append(item)
            item_index += 1
        # Comments must never be forgotten, so as a fail-safe, give the comments to the last
        # element if they were not assigned above. (items should not be false, check defensively
        # to avoid crash.)
        if item_count <= item_index and standalone_policy != "insert" and items:
            last_item = items[-1]
            list_onto_add = comments_by_item[last_item] = comments_by_item.get(last_item, [])

        list_onto_add.append(comment)
    new_items.extend(items[item_index:])
    return (new_items, comments_by_item)

class Node(object):
    def __init__(self, position, text = None):
        self.child_by_name = {}
        self.position = position
        self.text = text
        self.preceded_by_empty_line = False
        self.respects_preceding_empty_line = False
        self.comments = []
        # Controls whether gives comments to parent. Also controls with comment gets to be end of
        # line comment if many end of line comments.
        #   None: keeps the comment itself (or gives to child)
        #   1: keeps the comment with low priority
        #   2: keeps the comment with high priority
        self.priority_of_giving_parent_comments = None
    def after_parse(self, options):
        pass
    def _node_names(self):
        return filter(lambda x: x.startswith("p_"), dir(self))
    def __getitem__(self, name):
        return self.child_by_name[name]
    def __setitem__(self, name, value):
        self.child_by_name[name] = value
    # Return all nodes from the node tree as a flat list (depth-first order), so each
    # node will be in the order they appear in the cf file
    def descendants(self):
        descendants = []
        for child in self.children():
            descendants.extend([child] + child.descendants())
        return descendants
    def children(self):
        return sorted(filter(None, self.child_by_name.values()),
                      key = lambda node: node.position.parse_index)
    def give_comment_for_adoption(self, comments, parents):
        parents[-1].adopt_comments(comments, self.priority_of_giving_parent_comments, parents[:-1])
    def adopt_comments(self, comments, priority, parents):
        "Priority affects selection of end-of-line comment"
        if self.priority_of_giving_parent_comments:
            self.give_comment_for_adoption(comments, parents)
        else:
            for comment in comments:
                comment.priority = priority
            self.comments.extend(comments)
    def add_comments(self, comments, parents):
        # All the given comments must be assignable and be assigned, otherwise an error
        new_items, comments_by_item = items_and_comments_by_item(self.children(), comments,
                                                                 standalone_policy = "give_to_child")
        add_comments_to_items(new_items, comments_by_item, parents + [self])
    def start_line_number_with_comment(self):
        line_number = self.position.start_line_number
        if self.comments:
            # Comments are always appended, so the original comment for this node must be first.
            # If it is just preceding the node line, it must be the original comment (i.e., the
            # comment that appears in the line preceding the node). Any other comment was adopted
            # from a child node.
            if self.comments[0].position.end_line_number == line_number - 1:
                return self.comments[0].position.start_line_number
        return line_number
    def lines(self, options):
        def merged_comment(comments):
            merged_comment = copy.deepcopy(comments[0])
            for comment in comments[1:]:
                merged_comment.append_comment(comment)
            return merged_comment
        lines = self._preceding_empty_line(options)
        if self.comments: # optimisation, saves 30% of rendering time
            # Indentation assumes that first line of the child is indented by the parent, and any
            # following lines are intended by the child here, to given depth for this child, in options
            comment_options = options.child()
            tail_comment = find_in_list(lambda comment:
                                            (comment.is_end_of_line() and
                                             # In case the EOL comment was adopted (not at end of
                                             # this node's lines), consider it a standalone comment
                                             # (actual case: argument list's first element being a
                                             # comment on the same line on # which the opening brace
                                             # is).
                                             self.position.covers(comment.position.start_line_number)),
                                        reversed(sorted(self.comments,
                                                        key = lambda comment: comment.priority)))
            if tail_comment:
                tail_comment_lines = joined_lines([Line(" ")],
                                                  tail_comment.lines(comment_options))
            else:
                tail_comment_lines = []

            line_comments = [comment for comment in self.comments if comment != tail_comment]
            if line_comments:
                line_comment = merged_comment(line_comments)
                line_comment_lines = line_comment.lines(comment_options)
            else:
                line_comment_lines = []

            lines += (line_comment_lines
                      + joined_lines(self._lines(options),
                                     [Line("", end_comments = tail_comment_lines)]))
        else:
            lines += self._lines(options)
        options.indent_lines(lines)
        return lines
    def _preceding_empty_line(self, options):
        respects_empty_line = (options.respects_preceding_empty_line
                                  if options.respects_preceding_empty_line != None
                                  else self.respects_preceding_empty_line)
        return [Line("")] if self.preceded_by_empty_line and respects_empty_line else []
    def inspect(self):
        return re.sub(r"\n", " | ", str(self))
    def to_string(self, options):
        def string_from_line(line):
            string = line.string + "".join(map(lambda line: line.string, line.end_comments))
            # No indent for empty lines
            if string and line.indent:
                return " " * line.indent + string
            return string
        line_endings = options.line_endings or "\n"
        return line_endings.join(map(string_from_line, self.lines(options)))

class Block(Node):
    def __init__(self, position, element, type, name, args, block_child_list):
        super(Block, self).__init__(position)
        self["element"] = element
        self["type"] = type
        self["name"] = name
        self["args"] = args
        self["block_child_list"] = block_child_list
    def _lines(self, options):
        child_options = options.child()
        space = [Line(" ")]
        lines_until_args = joined_lines(self["element"].lines(child_options),
                                        space,
                                        self["type"].lines(child_options),
                                        space,
                                        self["name"].lines(child_options))
        return joined_lines(lines_until_args,
                            self["args"].lines(options.child(lines_until_args)),
                            space,
                            self["block_child_list"].lines(child_options))

class Body(Block):
    pass

class Bundle(Block):
    pass

class Comment(Node):
    def __init__(self, position, line, original_indentation, type = None):
        """
        type means affinity to other element.
        Valid values for type are 'end-of-line', 'standalone', or 'next-node'
        """
        super(Comment, self).__init__(position)
        self.text_lines = [line]
        self.type = type
        self.original_indentation = original_indentation
        self.priority = 0
    def is_end_of_line(self):
        return self.type == "end-of-line"
    def is_standalone(self):
        return self.type == "standalone"
    def prepend_line(self, position, line):
        if self.is_end_of_line():
            raise "End of line comments are one liners"
        self.text_lines.insert(0, line)
        self.position.start_line_number = position.start_line_number
        self.position.start_pos = position.start_pos
    def append_comment(self, comment):
        self.text_lines.extend(comment.text_lines)
        self.position.end_line_number = comment.position.end_line_number
        self.position.end_pos = comment.position.end_pos
    def _lines(self, options):
        # text without starting #
        def text_for_line(line):
            # No space in #-..., or #=... or ##...
            if len(line) <= 1 or re.match(r"^\#[\#\-=]", line):
                text = line[1:]
                separator = ""
            else:
                text, = re.match(r"\#[\t ]?(.*)", line).groups()
                separator = " "
            return Line("#%s" % separator + text, 0)
        return map(text_for_line, self.text_lines)

class PromiseType(Node):
    def __init__(self, position, name, class_promise_list):
        super(PromiseType, self).__init__(position)
        self["name"] = name
        self["class_promise_list"] = class_promise_list
    def name(self):
        return self["name"].name
    def len(self):
        return self["class_promise_list"].len()
    def _lines(self, options):
        # Avoid double line break when no promises
        if 0 < self["class_promise_list"].len():
            join_by = [Line("")] # line break
        else:
            join_by = []
        child_options = options.child();
        return joined_lines(self["name"].lines(child_options),
                            join_by + self["class_promise_list"].lines(child_options))

class Class(Node):
    def __init__(self, position, expression):
        super(Class, self).__init__(position)
        self.respects_preceding_empty_line = True
        self["expression"] = expression
    def _lines(self, options):
        return self["expression"].lines(options.child())

class Promise(Node):
    def __init__(self, position, promiser, arrow, promisee, maybe_comma, constraints, semicolon):
        super(Promise, self).__init__(position)
        self["promiser"] = promiser
        self["promisee"] = promisee
        self["maybe_comma"] = maybe_comma # This is never output
        self["constraints"] = constraints
        self["semicolon"] = semicolon;
        self.respects_preceding_empty_line = True
    def _lines(self, options):
        promisee_lines = []
        no_indent_options = options.child()

        promiser_lines = self["promiser"].lines(no_indent_options)

        # Options are:
        #   promisee -> promiser
        #
        # If too long:
        #   promiser_long
        #     -> promiser

        if self["promisee"]:
            promisee_lines = self["promisee"].lines(no_indent_options)
            def inline_promisee(options):
                return joined_lines(promiser_lines, [Line(" -> ")], promisee_lines)
            def lined_promisee(options):
                return joined_lines(promiser_lines,
                                    [Line(""), Line("-> ", TAB_SIZE)],
                                    promisee_lines)
            promiser_and_promisee = first_that_fits(options, [inline_promisee, lined_promisee])
        else:
            promiser_and_promisee = promiser_lines

        # Options are:
        #   promiser -> promisee
        #     constraint;
        #
        #   promiser constraint;
        #
        #   promiser # if long promiser
        #     constraint;
        #
        #   promiser
        #     constraint
        #     constraint;
        #

        def one_liner_string(options):
            constraints_options = options.child(promiser_lines, 1)
            constraints_options.may_line_break_constraint = False
            return joined_lines(promiser_and_promisee,
                                [Line(" ")],
                                self["constraints"].lines(constraints_options))
        def empty_list_string(options):
            return joined_lines(promiser_and_promisee, self["constraints"].lines(no_indent_options))
        def lined_string(options):
            return joined_lines(promiser_and_promisee,
                                # Line break, and then indent
                                [Line(""), Line("", TAB_SIZE)],
                                self["constraints"].lines(options.child(TAB_SIZE)))

        if (self["constraints"].len() == 1
            and not self["promisee"]
            and self["promiser"].position.start_line_number
                    == self["promiser"].position.end_line_number):
            # A single constraint may fit on the same line as the promise.
            # First try to fit on one line (without allowing line break in constraint), and if does
            # not fit, put the constraint on its own line (constraing will first try without line
            # break, then with it). If the promise is over multiple lines, don't make it a one liner.
            lines_fns = [one_liner_string, lined_string]
        elif self["constraints"].len() == 0:
            lines_fns = [empty_list_string]
        else:
            lines_fns = [lined_string]
        return first_that_fits(options, lines_fns)

class Constraint(Node):
    def __init__(self, position, type, assign, value, maybe_comma):
        super(Constraint, self).__init__(position)
        self["type"] = type
        self["assing"] = assign
        self["value"] = value
        self["maybe_comma"] = maybe_comma
    def _lines(self, options):
        type_lines = self["type"].lines(options.child())
        lines_fns = [lambda options:
                         # First try to fit all on the same line
                         joined_lines(type_lines,
                                      [Line(" => ")],
                                      # 4 for " => "
                                      self["value"].lines(options.child(type_lines, 4)))]
        if options.may_line_break_constraint:
            lines_fns.append(lambda options:
                                 # If does not fit, break after =>
                                 joined_lines(type_lines,
                                              [Line(" =>"), Line("", TAB_SIZE)],
                                              self["value"].lines(options.child(TAB_SIZE))))
        return first_that_fits(options, lines_fns)

# This is inside body { ... }
class Selection(Constraint):
    def __init__(self, *args):
        super(Selection, self).__init__(*args)
        self.respects_preceding_empty_line = True
    def _lines(self, options):
        return joined_lines(super(Selection, self)._lines(options), [Line(";")])

def first_that_fits(options, lines_fns):
    """
    Returns the first set of lines returned by the "make lines" function that fits into the available
    width"
    lines_fn signature: (options) -> [Line, ...]
    """
    lines = []
    for lines_fn in lines_fns:
        lines = lines_fn(options)
        if max_line_length(lines) <= options.available_width():
            break
    return lines

class ListBase(Node):
    def __init__(self, position, open_brace, items, trailing_comma, close_brace):
        super(ListBase, self).__init__(position)
        self.priority_of_giving_parent_comments = 1
        self["open_brace"] = open_brace
        self.items = items
        self["close_brace"] = close_brace
    def children(self):
        return filter(None, [self["open_brace"]] + self.items + [self["close_brace"]])
    def len(self):
        return len(self.items)
    def add_comments(self, comments, parents):
        if self["close_brace"]:
            close_brace_comments, comments = (
                partition(lambda comment:
                              self["close_brace"].position.start_pos < comment.position.start_pos,
                          comments))
        else:
            close_brace_comments = []

        new_items, comments_by_item = (
            items_and_comments_by_item(self.items, comments,
                                       standalone_policy = "insert",
                                       is_standalone_comment_for_node_fn =
                                           lambda node, comment:
                                              self.is_standalone_comment_for_node(node, comment)))

        if close_brace_comments:
            comments_by_item[self["close_brace"]] = close_brace_comments
            new_items_with_close_brace = new_items + [self["close_brace"]]
        else:
            new_items_with_close_brace = new_items

        add_comments_to_items(new_items_with_close_brace, comments_by_item, parents + [self])
        # Replace the item list with the list that contains standalone comments
        self.items = new_items
    def is_standalone_comment_for_node(self, item, comment):
        return False
    def _lines(self, options):
        return first_that_fits(options, map(lambda list_arg:
                                                lambda options: self._format_items(options, **list_arg),
                                            self.list_args()))
    def _format_items(self, options,
                      join_by = None,
                      prefix_by = None,
                      postfix_by = None,
                      empty = [""],
                      start = None,
                      end = None,
                      terminator = "",
                      end_terminator = "",
                      respects_preceding_empty_line_fn = lambda is_first: None, # None means ignored
                      depth_fn = lambda list, node: 0):
        join_by, prefix_by, postfix_by, empty, start, end = (
            map(lambda strings: list(map(Line, strings)) if strings else None,
                [join_by, prefix_by, postfix_by, empty, start, end]))

        def child_lines(node, terminator, index):
            # Avoid commas etc at the end of standalone comments
            if isinstance(node, Comment):
                terminator = ""

            is_first = index == 0

            depth = depth_fn(self, node)
            child_options = options.child(depth,
                                          respects_preceding_empty_line =
                                              respects_preceding_empty_line_fn(is_first))
            return joined_lines([Line("", depth)], node.lines(child_options), [Line(terminator)])
        if not self.items:
            return empty
        else:
            terminators = [terminator] * (len(self.items) - 1) + [end_terminator]
            # Want to say map(lambda (index, (terminator, node)) but cannot in Python 3
            child_line_arrays = list(map(lambda idx_and_terminator_node_pair:
                                             joined_lines(prefix_by,
                                                          child_lines(idx_and_terminator_node_pair[1][1],
                                                                      idx_and_terminator_node_pair[1][0],
                                                                      idx_and_terminator_node_pair[0]),
                                                          postfix_by),
                                         enumerate(zip(terminators, self.items))))
            children_lines = reduce(lambda joined, lines: joined_lines(joined, join_by, lines),
                                     child_line_arrays[1:],
                                     child_line_arrays[0])
            return joined_lines(start, children_lines, end)

LINE_BREAK = ["", ""]

class InlinableList(ListBase):
    def inlinable(self):
        has_comments = find_in_list(lambda node: node.comments or isinstance(node, Comment),
                                    self.items)
        return not has_comments
    def list_args(self):
        inlined_args, lined_args = self._inlined_and_lined_list_args()
        if not self.inlinable():
            return [lined_args]
        elif  1 < len(self.items): # don't line-break a list with just one element
            return [inlined_args, lined_args]
        else:
            return [inlined_args]
    def _inlined_and_lined_list_args(self):
        """
        Return a pair of list args, first for inlining the list,
        and second for having line breaks between elements
        """
        raise RuntimeError("To be implemented by deriving class")

LIST_ARGS = ({ "join_by" : [" "],
               "terminator" : ",",
               "empty" : ["{}"],
               "start" : ["{ "],
               "end" : [" }"],
               "respects_preceding_empty_line_fn" : lambda is_first: False },
             # lined version
             { "postfix_by" : LINE_BREAK,
               "terminator" : ",",
               "end_terminator" : ",",
               "empty" : ["{}",],
               "start" : ["{", ""],
               "end" : ["}"],
               "respects_preceding_empty_line_fn" : lambda is_first: not is_first })
class List(InlinableList):
    def _inlined_and_lined_list_args(self):
        return LIST_ARGS

ARGUMENT_LIST_ARGS = ({ "join_by" : [" "],
                        "terminator" : ",",
                        "start" : ["("],
                        "end" : [")"] },
                      { "join_by" : LINE_BREAK,
                        "terminator" : ",",
                        "end_terminator" : ")",
                        "start" : ["("],
                        # 1 == len("(") })
                        "depth_fn" : lambda list, node: 1 })
class ArgumentList(InlinableList):
    def _inlined_and_lined_list_args(self):
        return ARGUMENT_LIST_ARGS

class Specification(ListBase):
    def list_args(self):
        return [{ "join_by" : LINE_BREAK,
                  "postfix_by" : LINE_BREAK }]

def class_list_depth_fn(default_class_tab_depth, class_of_intended_node):
    def class_list_depth(list, node):
        """
        Tab depth function (for ListBase list_arg) for when list constains Classes and something else.
        Indents classes by one, and promises by 2. Comments are indented based on their original
        indentation, to appear either as children to classes or promise type
        """
        def tab_depth():
            if isinstance(node, Class):
                return 1
            elif isinstance(node, Comment):
                # Default indentation for Class is 2 * tab space, so assume anything above that to be
                # on promise level. Also, it there are any promises before the next class, assume
                # the comment belongs to the promise level.
                comment_index = list.items.index(node)
                has_previous_intended_node = find_index(isinstance_fn(class_of_intended_node),
                                                        list.items,
                                                        start_index = comment_index,
                                                        reverse = True) != None
                next_class_index = find_index(isinstance_fn(Class), list.items,
                                              start_index = comment_index, not_found = sys.maxsize)
                next_promise_index = find_index(isinstance_fn(class_of_intended_node), list.items,
                                                start_index = comment_index, not_found = sys.maxsize)
                if next_promise_index < next_class_index:
                    return 2
                if not has_previous_intended_node:
                    return 1
                return 1 if node.original_indentation <= TAB_SIZE * default_class_tab_depth else 2
            else:
                return 2
        return tab_depth() * TAB_SIZE
    return class_list_depth

def merged_dicts(*dicts):
    return dict(chain(*map(lambda d: d.items(), dicts)))

# This is a respects_preceding_empty_line_fn function
def does_not_respect_empty_line_before_first_item(is_first):
    return False if is_first else None

PROMISE_TYPE_LIST_ARGS, CLASS_SELECTION_LIST_ARGS = (
  map(lambda dict: [merged_dicts(dict, { "postfix_by" : LINE_BREAK,
                                         "empty" : ["{", "}"],
                                         "start" : ["{", ""],
                                         "end" : ["}"] })],
                                 [{ "join_by" : LINE_BREAK,
                                    "depth_fn" : lambda list, node: TAB_SIZE },
                                  { "depth_fn" : class_list_depth_fn(1, Selection),
                                    "respects_preceding_empty_line_fn" :
                                        # Never empty line before the first class or selection
                                        does_not_respect_empty_line_before_first_item }]))
EVALUATION_ORDER = ["meta:",
                    "vars:",
                    "defaults:",
                    "classes:",
                    # agent bundle only
                    "users:",
                    "files:",
                    "packages:",
                    "guest_environments:",
                    "methods:",
                    "processes:",
                    "services:",
                    "commands:",
                    "storage:",
                    "databases:",
                    # server bundle only
                    "access:",
                    "roles:",
                    # monitor bundle only
                    "measurements:",
                    # edit_line only
                    "delete_lines:",
                    "field_edits:",
                    "insert_lines:",
                    "replace_patterns:",
                    # common
                    "reports:"]
# Items should be PromiseTypes or Comments
class PromiseTypeList(ListBase):
    def after_parse(self, options):
        super(PromiseTypeList, self).after_parse(options)
        if options.removes_empty_promise_types:
            self.items = self._empty_promise_types_removed(self.items)
        if options.sorts_promise_types_to_evaluation_order:
            self.items = self._sorted_to_cfengine_evaluation_order(self.items)
    def _empty_promise_types_removed(self, items):
        def has_comments(promise_type):
            # comments are not under the node directly (are under p_name,
            # but check all for robustness)
            return find_in_list(lambda node: node.comments,
                                [promise_type] + promise_type.children())
        return list(filter(lambda node:
                               (not isinstance(node, PromiseType)
                                or node.len() != 0 # has classes or promises?
                                or has_comments(node)),
                           items))
    def _sorted_to_cfengine_evaluation_order(self, items):
        def promise_index(promise_type):
            try:
                return EVALUATION_ORDER.index(promise_type.name())
            except ValueError:
                return sys.maxsize

        def with_interleaved_comments(sorted_promise_types, unordered_items, comments):
            interleaved_items = copy.copy(sorted_promise_types)
            # process in reverse order, so that interleaved_items always contains the next item,
            # even if comments follow comments
            for comment in reversed(comments):
                original_index = unordered_items.index(comment)
                if original_index == len(unordered_items) - 1: # last?
                    # last comment stays last
                    new_index_of_item = len(interleaved_items)
                else:
                    next_item = unordered_items[original_index + 1]
                    new_index_of_item = interleaved_items.index(next_item)
                interleaved_items.insert(new_index_of_item, comment)
            return interleaved_items

        # Sort promises first, then put the comments before the items they were original before
        promise_types, comments = partition(isinstance_fn(PromiseType), items)
        sorted_promise_types = sorted(promise_types, key = promise_index)
        return with_interleaved_comments(sorted_promise_types, items, comments)
    def list_args(self):
        return PROMISE_TYPE_LIST_ARGS
    def is_standalone_comment_for_node(self, item, comment):
        # The indentation for promise type is 1 * tab size, so assume anything above that belongs
        # to the node
        return TAB_SIZE < comment.original_indentation

class ClassAndSomethingList(ListBase):
    def after_parse(self, options):
        super(ClassAndSomethingList, self).after_parse(options)
        # Never an empty line between class and its first promise
        previous_item = None
        for item in self.items:
            # No line break right after class, unless followed by another class
            if isinstance(previous_item, Class) and not isinstance(item, Class):
                item.respects_preceding_empty_line = False
            # Comments should respect their line breaks
            elif isinstance(item, Comment):
                item.respects_preceding_empty_line = True
            previous_item = item

# Items should be Classes, Selections or Comments.
class ClassSelectionList(ClassAndSomethingList):
    def list_args(self):
        return CLASS_SELECTION_LIST_ARGS

# Promises are indented as if they are under classes in tree, so deeper
CLASS_PROMISE_LIST_ARGS = [{ "depth_fn" : class_list_depth_fn(2, Promise),
                             # Never empty line before the first class, promise or comment
                             "respects_preceding_empty_line_fn" :
                                does_not_respect_empty_line_before_first_item,
                             "join_by" : LINE_BREAK }]
# for Bundle, elements should be PromiseTypes. For Body, they should be Classes or Selections.
class ClassPromiseList(ClassAndSomethingList):
    def list_args(self):
        return CLASS_PROMISE_LIST_ARGS

CONSTRAINT_LIST_ARGS = [{ "empty" : [";"],
                          "join_by" : LINE_BREAK,
                          "terminator" : ",",
                          "end_terminator" : ";" }]
class ConstraintList(ListBase):
    def list_args(self):
        return CONSTRAINT_LIST_ARGS

class Function(Node):
    def __init__(self, position, name, args):
        super(Function, self).__init__(position)
        self["name"] = name
        self["args"] = args
    def _lines(self, options):
        name_lines = self["name"].lines(options.child())
        return joined_lines(name_lines, self["args"].lines(options.child(name_lines)))

class String(Node):
    def __init__(self, position, name):
        super(String, self).__init__(position)
        self.name = name
    def _lines(self, options):
        return [Line(self.name, 0)]
    def add_comments(self, comments, parents):
        if self.priority_of_giving_parent_comments:
            self.give_comment_for_adoption(comments, parents)
        else:
            self.comments = comments
