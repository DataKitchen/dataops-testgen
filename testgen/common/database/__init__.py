from collections.abc import Iterable
from io import StringIO


class FilteredStringIO(StringIO):
    def __init__(self, filtered: Iterable[str], *args, **kwargs):
        self._replacements = str.maketrans(dict.fromkeys(filtered or [], ""))
        super().__init__(*args, **kwargs)

    def write(self, to_write: str):
        return super().write(to_write.translate(self._replacements))
