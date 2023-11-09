from django.test import TestCase
from utils.bibtex import BibTeXParser
from ..schema import generate_json_for_bibtex_entry


class SchemaTests(TestCase):
    def test_generate_json_for_bibtex_entry_conference_paper(self):
        bib_string = """
@inproceedings{deng_imagenet_2009,
  address = {Miami, FL},
  title = {{ImageNet}: {A} large-scale hierarchical image database},
  isbn = {978-1-4244-3992-8},
  shorttitle = {{ImageNet}},
  url = {https://ieeexplore.ieee.org/document/5206848/},
  doi = {10.1109/CVPR.2009.5206848},
  urldate = {2023-11-02},
  booktitle = {2009 {IEEE} {Conference} on {Computer} {Vision} and {Pattern} {Recognition}},
  publisher = {IEEE},
  author = {Deng, Jia and Dong, Wei and Socher, Richard and Li, Li-Jia and {Kai Li} and {Li Fei-Fei}},
  month = jun,
  year = {2009},
  pages = {248--255},
}
"""

        entries = BibTeXParser.parse_bibtext_as_string(bib_string)

        result = generate_json_for_bibtex_entry(entries[0])

        self.assertEqual(result['title'], 'ImageNet: A large-scale hierarchical image database')
        self.assertEqual(result['publisher-place'], 'Miami, FL')
        self.assertEqual(result['publisher'], 'IEEE')
        self.assertEqual(result['type'], 'paper-conference')
        self.assertEqual(result['page'], '248–255')
        self.assertEqual(result['container-title'], '2009 IEEE Conference on Computer Vision and Pattern Recognition')
        self.assertEqual(result['DOI'], '10.1109/CVPR.2009.5206848')
        self.assertEqual(result['author'][0]['family'], 'Deng')
        self.assertEqual(result['author'][0]['given'], 'Jia')

        self.assertEqual(result['issued']['date-parts'][0][0], 2009)
        self.assertEqual(result['issued']['date-parts'][0][1], 6)

    def test_generate_json_for_bibtex_entry_journal_article(self):
        """
        Tests additional things like URL parsing, LaTeX parsing, special chars.
        """
        bib_string = """
@article{Gulisano2018,
author = {Gulisano, Walter and Maugeri, Daniele and Baltrons, Marian A. and F{\`{a}}, Mauro and Amato, Arianna and Palmeri, Agostino and D'Adamio, Luciano and Grassi, Claudio and Devanand, D.P. and Honig, Lawrence S. and Puzzo, Daniela and Arancio, Ottavio},
doi = {10.3233/JAD-179935},
editor = {Perry, G. and Avila, J. and Moreira, P.I. and Sorensen, A.A. and Tabaton, M.},
file = {:C\:/Users/tdiorio/AppData/Local/Mendeley Ltd./Mendeley Desktop/Downloaded/Gulisano et al. - 2018 - Role of Amyloid-$\beta$ and Tau Proteins in Alzheimer's Disease Confuting the Amyloid Cascade.pdf:pdf},
issn = {13872877},
journal = {Journal of Alzheimer's Disease},
keywords = {Amyloid-$\beta$ peptide,amyloid-$\beta$ protein precursor,oligomers,synaptic dysfunction,tau},
month = {jun},
number = {s1},
pages = {S611--S631},
pmid = {29865055},
title = {{Role of Amyloid-$\beta$ and Tau Proteins in Alzheimer's Disease: Confuting the Amyloid Cascade}},
url = {https://www.medra.org/servlet/aliasResolver?alias=iospress&doi=10.3233/JAD-179935},
volume = {64},
year = {2018}
}
"""

        entries = BibTeXParser.parse_bibtext_as_string(bib_string)

        result = generate_json_for_bibtex_entry(entries[0])

        self.assertEqual(result['type'], 'article-journal')
        self.assertEqual(result['volume'], '64')
        self.assertEqual(result['issue'], 's1')
        self.assertEqual(result['URL'], 'https://www.medra.org/servlet/aliasResolver?alias=iospress&doi=10.3233/JAD-179935')
        # author with first name Mauro has a LaTeX accent in their last name
        for author in result['author']:
            if author['given'] == 'Mauro':
                self.assertEqual(author['family'], 'Fà')
                break

    # Test for other types of entries to ensure our schema is robust

    def test_generate_json_for_bibtex_entry_book(self):
        bib_string = """
@book{knuth84,
    author    = "Donald E. Knuth",
    title     = "The {TeX}book",
    publisher = "Addison-Wesley",
    year      = "1984",
}
"""

        entries = BibTeXParser.parse_bibtext_as_string(bib_string)

        result = generate_json_for_bibtex_entry(entries[0])

        self.assertEqual(result['type'], 'book')
        self.assertEqual(result['title'], 'The TeXbook')
        self.assertEqual(result['publisher'], 'Addison-Wesley')
        self.assertEqual(result['issued']['date-parts'][0][0], 1984)

    def test_generate_json_for_bibtex_entry_online(self):
        bib_string = """
@online{example,
    author = "Some Author",
    title  = "Page with {{multiple}} {{special}} characters",
    year   = "2021",
    url    = "https://example.com/path?query=parameter#section",
}
"""

        entries = BibTeXParser.parse_bibtext_as_string(bib_string)

        result = generate_json_for_bibtex_entry(entries[0])

        self.assertEqual(result['type'], 'webpage')
        self.assertEqual(result['title'], 'Page with multiple special characters')
        self.assertEqual(result['URL'], 'https://example.com/path?query=parameter#section')
        self.assertEqual(result['issued']['date-parts'][0][0], 2021)

    def test_generate_json_for_bibtex_entry_misc(self):
        bib_string = """
@misc{wiki,
    author = "{Wikipedia contributors}",
    title = "BibTeX --- Wikipedia{,} The Free Encyclopedia",
    year = "2020",
    url = "https://en.wikipedia.org/w/index.php?title=BibTeX&oldid=957077279",
    note = "[Online; accessed 22-May-2020]"
}
"""

        entries = BibTeXParser.parse_bibtext_as_string(bib_string)

        result = generate_json_for_bibtex_entry(entries[0])

        self.assertEqual(result['type'], 'document')
        self.assertEqual(result['title'], 'BibTeX — Wikipedia, The Free Encyclopedia')
        self.assertEqual(result['URL'], 'https://en.wikipedia.org/w/index.php?title=BibTeX&oldid=957077279')
        self.assertEqual(result['issued']['date-parts'][0][0], 2020)
