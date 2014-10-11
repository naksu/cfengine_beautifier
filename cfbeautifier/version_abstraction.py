import sys

if sys.version_info[0] < 3:
    text_class = unicode

    def string_from_file(path):
        with open(path, "r") as file:
            return string_from_stream(file)

    def string_from_stream(stream):
        return stream.read().decode('utf-8-sig')

    def write_stream(stream, output):
        stream.write(output.encode("utf-8"))

else:
    text_class = str

    def string_from_file(path):
        with open(path, "r", encoding = "utf-8-sig") as file:
            return string_from_stream(file)

    def string_from_stream(stream):
        return stream.read()

    def write_stream(stream, output):
        stream.write(output)
