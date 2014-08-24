from __future__ import absolute_import
from __future__ import unicode_literals
import re

class Color:
    DARK_GRAY = "1;30"
    DARK_RED = "22;31"
    DARK_GREEN = "22;32"
    DARK_YELLOW = "22;33"
    DARK_BLUE = "22;34"
    DARK_MAGENTA = "22;35"
    DARK_CYAN = "22;36"
    DARK_WHITE = "22;37" # same as gray
    GRAY = "22;37"
    RED = "1;31"
    GREEN = "1;32"
    YELLOW = "1;33"
    BLUE = "1;34"
    MAGENTA = "1;35"
    CYAN = "1;36"
    WHITE = "1;37"

    @staticmethod
    def colored(string, code):
        return "\033[%sm%s\033[0m" % (code, string)

    @staticmethod
    def strip(string):
        return re.sub("\033\[\d+.*?m", "", string)

# Declare method for each color in Color calss
for color in filter(lambda color: color.upper() == color, dir(Color)):
    def make_fn(color):
        color_code = Color.__dict__[color]
        def fn(string):
            return Color.colored(string, color_code)
        fn.__name__ = str(color.lower())  # str for Python 2
        return fn
    fn = make_fn(color)
    setattr(Color, fn.__name__, staticmethod(fn))
