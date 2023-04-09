import unittest
import requests_mock

from resolver import *
from web_scraping import *

@requests_mock.Mocker()
class ResolverTestCase(unittest.TestCase):
    def test_scihub(self, m):
        meta = {}
        with open("testdata/resolver_scihub.html") as f:
            canned_resp = f.read()
            doi = "10.1109/BioCAS.2015.7348414"
            self.assertEqual(f"https://sci-hub.se/{doi}", SciHubResolver.from_doi(doi))
            m.get(f"https://sci-hub.se/{doi}", text=canned_resp)

            meta = SciHubResolver.fetch_by_doi(doi)
            self.assertEqual({
                'doi': doi,
                'pdf_url': 'https://moscow.sci-hub.se/4746/234245eed78d3448735c796a77f10f85/laiho2015.pdf',
                }, meta)

        with open("testdata/laiho2015.pdf", 'rb') as pdf:
            m.get(meta['pdf_url'],
                  headers={'Content-Type': 'application/pdf'},
                  body=pdf)
            pdf_content = fetch_pdf(meta['pdf_url'])
            self.assertEqual(578565, len(pdf_content))

    def test_researchgate(self, m):
        meta = {}
        with open("testdata/resolver_researchgate.html") as f:
            canned_resp = f.read()
            url = "https://www.researchgate.net/publication/362385659_Haptic_Teleoperation_of_High-dimensional_Robotic_Systems_Using_a_Feedback_MPC_Framework"
            m.get(url, text=canned_resp)

            meta = fetch(url)
            self.assertEqual({
                    'doi': '10.48550/arXiv.2207.14635',
                    'pdf_url': 'https://www.researchgate.net/publication/362385659_Haptic_Teleoperation_of_High-dimensional_Robotic_Systems_Using_a_Feedback_MPC_Framework/fulltext/62e760583c0ea87887724795/Haptic-Teleoperation-of-High-dimensional-Robotic-Systems-Using-a-Feedback-MPC-Framework.pdf',
                }, meta)

        with open("testdata/haptic.pdf", 'rb') as pdf:
            m.get(meta['pdf_url'],
                  headers={'Content-Type': 'application/pdf'},
                  body=pdf)
            pdf_content = fetch_pdf(meta['pdf_url'])
            self.assertEqual(2199552, len(pdf_content))  # The byte size should match.

    def test_default_resolver(self, m):
        # Ensure we can still scan the text of the web page and pick the first doi-like stuff.
        meta = {}
        with open("testdata/resolver_scihub.html") as f:
            canned_resp = f.read()
            m.get(f"mock://default", text=canned_resp)

            meta = fetch("mock://default")
            self.assertEqual("10.1109/BioCAS.2015.7348414", meta['doi'])


if __name__ == '__main__':
    unittest.main()