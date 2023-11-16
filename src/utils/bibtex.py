import re
from dataclasses import dataclass, fields

import bibtexparser
from pylatexenc.latex2text import LatexNodes2Text


@dataclass
class BibTeXFields:
    # BibTeX format specification: https://www.bibtex.com/format
    # Additional fields: https://retorque.re/zotero-better-bibtex/exporting/extra-fields/
    address: str = None
    annote: str = None
    author: str = None
    booktitle: str = None
    bookauthor: str = None
    chapter: str = None
    doi: str = None
    edition: str = None
    editor: str = None
    howpublished: str = None
    medium: str = None
    institution: str = None
    issn: str = None
    isbn: str = None
    journal: str = None
    journalabbreviation: str = None
    archivelocation: str = None
    archive: str = None
    month: str = None
    note: str = None
    number: str = None
    organization: str = None
    language: str = None
    pages: str = None
    publisher: str = None
    school: str = None
    type: str = None
    series: str = None
    title: str = None
    shorttitle: str = None
    url: str = None
    volume: str = None
    year: str = None
    callnumber: str = None

    def __getitem__(self, key, default=None):
        return getattr(self, key, default)

    def get(self, key, default=None):
        return getattr(self, key, default)


@dataclass
class BibTeXEntry:
    key: str
    entry_type: str
    fields_dict: BibTeXFields

    def __getitem__(self, key, default=None):
        return getattr(self, key, default)

    def get(self, key, default=None):
        return getattr(self, key, default)


class BibTeXParser:
    """
    We use `bibtexparser` to parse BibTex files.

    We use a custom BibTeX parser to parse BibTeX strings as CSL.
    Since public libraries were insufficiently robust and had complex interfaces.
    Although we do borrow heavily from https://github.com/brechtm/citeproc-py
    """

    #  Meant to match URLs but be sensitive to avoid matching DOIs and BibTeX fields.
    #
    # Finds matches in:
    # - https://www.example.com
    # - https://www.example.com/search?q=openai
    # - http://www.example.com/path/to/resource
    # - https://doi.org/10.1000/xyz123
    # - https://www.example.com/path(to)resource
    # - http://www.example.com:8080/search?q=openai
    # - The website is available at http://www.example.com.
    # - https://www.example.com/path#section
    # - @misc{key, title = "Example", url = "https://www.example.com"}
    #
    # Does not find matches in:
    # - example.com/path
    # - 10.1000/xyz123
    # - ftp://ftp.example.com/resource
    # - \\usepackage{hyperref}
    # - See section 10.2.3/4 for details.
    # - @article{key, author = "Doe, J.", title = "Title", doi = "10.1000/xyz123"}
    url_pattern = re.compile(
        r'\bhttps?://[^\s()<>]+(?:\([\w\d]+\)|[^\s`!()\[\]{};:\'".,<>?«»“”‘’])*'
    )

    @staticmethod
    def parse_bibtext_as_string(bibtex_string):
        """
        Intended to parse a complete BibTeX file.
        """
        bib = bibtexparser.parse_string(bibtex_string)

        # Get the field names defined in the dataclass
        defined_fields = {f.name.lower() for f in fields(BibTeXFields)}

        entries = []

        for entry in bib.entries:
            # Filter out fields not defined in the dataclass and convert field names to lowercase
            filtered_fields = {
                k.lower(): v for k, v in entry.items() if k.lower() in defined_fields
            }

            fields_dict = BibTeXFields(**filtered_fields)
            # Create an instance of BibTeXEntry with the key, entry type, and fields
            bib_entry = BibTeXEntry(
                key=entry.key, entry_type=entry.entry_type, fields_dict=fields_dict
            )

            entries.append(bib_entry)

        return entries

    @staticmethod
    def parse_authors_to_json(author_string):
        """
        Parse a BibTeX author string into a list of CSL authors.
        """
        csl_authors = []
        for author in split_names(author_string):
            first, von, last, jr = parse_name(author)
            csl_parts = {}
            for part, csl_label in [
                (first, "given"),
                (von, "non-dropping-particle"),
                (last, "family"),
                (jr, "suffix"),
            ]:
                if part is not None:
                    csl_parts[csl_label] = LatexNodes2Text().latex_to_text(part)

            csl_author = {}
            if "family" in csl_parts:
                csl_author["family"] = csl_parts["family"]
            if "given" in csl_parts:
                csl_author["given"] = csl_parts["given"]
            if "non-dropping-particle" in csl_parts:
                csl_author["non-dropping-particle"] = csl_parts["non-dropping-particle"]
            if "suffix" in csl_parts:
                csl_author["suffix"] = csl_parts["suffix"]
            csl_authors.append(csl_author)
        return csl_authors

    @staticmethod
    def parse_string(bibtex_string):
        """
        Parse a BibTeX string into a readable string.
        """

        def make_string(string, top_level_group=False):
            # Skip latex processing if it's a URL
            # since LatexNodes2Text().latex_to_text() will mess up URLs
            if BibTeXParser.url_pattern.search(string):
                return string

            unlatexed = LatexNodes2Text().latex_to_text(string)
            # fixed_case = top_level_group and not string.startswith('\\')
            return unlatexed

        if bibtex_string is None:
            return None

        output = ""
        level = 0
        string = ""
        for char in bibtex_string:
            if char == "{":
                if level == 0:
                    if string:
                        output += make_string(string)
                        string = ""
                level += 1
            elif char == "}":
                level -= 1
                if level == 0:
                    output += make_string(string, True)
                    string = ""
            else:
                string += char
        if level != 0:
            raise SyntaxError('Non-matching braces in "{}"'.format(bibtex_string))
        if string:
            output += make_string(string)

        return output

    @staticmethod
    def parse_date_parts_from_date(
        year=None,
        month=None,  # string
        day=None,
    ):
        """
        Parse a BibTeX date string into a list of date parts.
        e.g. 2019, Jun 01 -> [2019, 6, 1]
        """
        if year is None or year == "":
            return None

        date_parts = [int(year)]

        if month is not None and month != "":
            # convert month to number
            month = month.lower()
            if month not in MONTH_TO_NUMBER:
                return date_parts

            date_parts.append(MONTH_TO_NUMBER[month])

            if day is not None and day != "":
                date_parts.append(int(day))

        return date_parts


MONTH_TO_NUMBER = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


# BibTeX name handling. Inspired by: https://github.com/brechtm/citeproc-py/blob/master/citeproc/source/bibtex/bibtex.py
#
# references
#  - BibTeXing by Oren Patashnik (Feb 8, 1988), 4. Helpful Hints, item 18
#    (BibTeX 0.99d - http://www.ctan.org/tex-archive/biblio/bibtex/base/btxdoc.pdf)
#  - A summary of BibTex by Xavier Décoret
#    (http://maverick.inria.fr/~Xavier.Decoret/resources/xdkbibtex/bibtex_summary.html)
#  - Tame the BeaST by Nicolas Markey
#    (http://tug.ctan.org/info/bibtex/tamethebeast/ttb_en.pdf)

AND = " and "


def split_names(string):
    """Split a string of names separated by 'and' into a list of names."""
    if not string:
        return []

    brace_level = 0
    names = []
    last_index = 0
    for i in range(len(string)):
        char = string[i]
        if brace_level == 0 and string[i:].startswith(AND):
            names.append(string[last_index:i])
            last_index = i + len(AND)
        elif char == "{":
            brace_level += 1
        elif char == "}":
            brace_level -= 1
    last_name = string[last_index:]
    if last_name:
        names.append(last_name)
    return names


def parse_name(name):
    """Parse a BibTeX name string and split it into First, von, Last and Jr
    parts.
    """
    parts = split_name(name)
    if len(parts) == 1:  # First von Last
        (first_von_last,) = parts
        index = 0
        first, jr = [], []
        for word in first_von_last[:-1]:
            if is_capitalized(word) not in (True, None):
                break
            first.append(word)
            index += 1
        von_last = first_von_last[index:]
    elif len(parts) == 2:  # von Last, First
        jr = []
        von_last, first = parts
    elif len(parts) == 3:  # von Last, Jr, First
        von_last, jr, first = parts
    von, last = split_von_last(von_last)
    join = " ".join
    return join(first) or None, join(von) or None, join(last), join(jr) or None


def split_name(name):
    """Split a name in into parts delimited by commas (at brace-level 0), and
    each part into words.

    Returns a list of of lists of words.
    """
    brace_level = 0
    parts = []
    current_part = []
    word = ""
    for char in name:
        if char in " \t,":
            if brace_level == 0:
                if word:
                    current_part.append(word)
                    word = ""
                if char == ",":
                    parts.append(current_part)
                    current_part = []
                continue
        elif char == "{":
            brace_level += 1
        elif char == "}":
            brace_level -= 1
        word += char
    if word:
        current_part.append(word)
        parts.append(current_part)
    return parts


def is_capitalized(string):
    """Check if a BibTeX substring is capitalized.

    A string can be "case-less", in which case `None` is returned.
    """
    brace_level = 0
    special_char = False
    for char, next_char in lookahead_iter(string):
        if (brace_level == 0 or special_char) and char.isalpha():
            return char.isupper()
        elif char == "{":
            brace_level += 1
            if brace_level == 1 and next_char == "\\":
                special_char = True
        elif char == "}":
            brace_level -= 1
            if brace_level == 0:
                special_char = False
    return None  # case-less


def split_von_last(words):
    """Split "von Last" name into von and Last parts."""
    if len(words) > 1 and is_capitalized(words[0]) is False:
        for j, word in enumerate(reversed(words[:-1])):
            if is_capitalized(word) not in (True, None):
                return words[: -j - 1], words[-j - 1 :]
    return [], words


def lookahead_iter(iterable):
    """Iterator that also yields the next item along with each item. The next
    item is `None` when yielding the last item.
    """
    items = iter(iterable)
    item = next(items)
    for next_item in items:
        yield item, next_item
        item = next_item
    yield item, None
