import sys
import sublime, sublime_plugin

if sys.version_info[0] < 3:
    from cfbeautifier import beautifier
    from cfbeautifier.util import ParserError
else:
    from .cfbeautifier import beautifier
    from .cfbeautifier.util import ParserError

STATUS_KEY = 'cfengine-beautifier'

def settings():
    return sublime.load_settings('CFEngineBeautifier.sublime-settings')

def is_cfengine_file(file_name):
    return file_name.endswith(".cf")

class BeautifyCfengineEventListener(sublime_plugin.EventListener):
    def on_pre_save(self, view):
        if settings().get('beautify_on_save', True):
            view.run_command("beautify_cfengine")
    def on_modified(self, view):
        view.erase_regions("parser_errors")

class BeautifyCfengineCommand(sublime_plugin.TextCommand):
    def run(self, edit, moves_cursor = True):
        if is_cfengine_file(self.view.file_name()):
            buffer_region = sublime.Region(0, self.view.size())
            self.view.set_status(STATUS_KEY, "");
            try:
                view_state = self.viewport_state()
                self.view.replace(edit,
                                  buffer_region,
                                  beautifier.beautified_string(self.view.substr(buffer_region),
                                                              options = self.options()))
                self.set_viewport_state(view_state)
            except ParserError as error:
                error_region = sublime.Region(error.position, error.position + len(error.fragment))
                self.view.add_regions("parser_errors", [error_region], "invalid.illegal", "circle")
                if moves_cursor:
                    self.view.sel().clear()
                    self.view.sel().add(sublime.Region(error.position))
                    self.view.show_at_center(error_region)
                self.view.set_status(STATUS_KEY, str(error));
            else:
                self.view.erase_regions("parser_errors")

    def options(self):
        the_settings = settings()
        options = beautifier.Options()
        options.page_width = the_settings.get("page_width", 100)
        # Note the trailing s before verbs is (intentionally) different in setting and option
        options.removes_empty_promise_types = the_settings.get("remove_empty_promise_types", True)
        options.sorts_promise_types_to_evaluation_order = (
            the_settings.get("sort_promise_types_to_evaluation_order", True))
        # Assuming support for OS 9 line endings is not needed
        options.line_endings = "\r\n" if self.view.line_endings() == "Windows" else "\n"
        return options

    def viewport_state(self):
        return { "selections" : map(lambda region: (region.a, region.b), self.view.sel()),
                 "positions" : self.view.viewport_position() }

    def set_viewport_state(self, state):
        self.view.set_viewport_position((0, 0,), False)
        self.view.set_viewport_position(state["positions"], False)
        self.view.sel().clear()
        for (a, b) in state["selections"]:
            self.view.sel().add(sublime.Region(a, b))
