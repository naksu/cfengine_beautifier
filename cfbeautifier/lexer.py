from __future__ import absolute_import
from __future__ import unicode_literals
from .util import ParserError
from .ply import lex

t_ARROW = r"->"
t_ASSIGN = r"=>"
t_COMMA = r","
t_OPEN_BRACE = r"{"
t_CLOSE_BRACE = r"}"
t_OPEN_PAREN = r"\("
t_CLOSE_PAREN = r"\)"
t_SEMICOLON = r";"
t_NAKEDVAR = r"[$@][(][a-zA-Z0-9_\[\]\200-\377.:]+[)]|[$@][{][a-zA-Z0-9_\[\]\200-\377.:]+[}]"

keywords = {
   "body" : "BODY",
   "bundle" : "BUNDLE",
}

def t_QSTRING(t):
    r"\"((\\(.|\n))|[^\"\\])*\"|\'((\\(.|\n))|[^'\\])*\'|`[^`]*`"
    t.lexer.lineno += t.value.count("\n")
    return t

def t_CLASS(t):
    r"[.|&!()a-zA-Z0-9_\200-\377:]+::"
    return t

# Must be before promise type
def t_SYMBOL(t):
    r"[a-zA-Z0-9_\200-\377]+[:][a-zA-Z0-9_\200-\377]+"
    return t

def t_PROMISE_TYPE(t):
    r"[a-zA-Z_]+:"
    return t

def t_IDSYNTAX(t):
    r"[a-zA-Z0-9_\200-\377]+"
    t.type = keywords.get(t.value, t.type)
    return t

def t_space(t):
    r"[ \t]+"
    pass

def t_newline(t):
    r'\r?\n+'
    t.lexer.lineno += t.value.count("\n")

def t_comment(t):
    r'\#.*'
    # Strip \r (part of windows line ending) from the comment
    t.value = t.value.rstrip()
    t.lexer.comments.append(t)

def t_error(t):
    raise ParserError(t.value, t.lineno, t.lexer.lexdata, t.lexpos)

tokens = ([token for token in [id[2:] for id in globals().keys() if id.startswith("t_")]
               # exclude t_error, etc
               if token.upper() == token] +
           list(keywords.values()))

def lexer():
    the_lex = lex.lex()
    the_lex.comments = []
    return the_lex
