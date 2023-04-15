from collections import namedtuple
import unittest
import requests_mock

from resolver import *
from web_scraping import *

TestCase = namedtuple('TestCase', ["doi", "mock_file", "url", "pdf_url"])

SCIHUB_CASES = [
    TestCase(
        "10.1109/BioCAS.2015.7348414",
        "testdata/scihub0.html",
        "https://sci-hub.se/10.1109/BioCAS.2015.7348414",
        "https://zero.sci-hub.se/4746/234245eed78d3448735c796a77f10f85/laiho2015.pdf"),
    TestCase(
        "10.3389/frai.2020.00004",
        "testdata/scihub1.html",
        "https://sci-hub.se/10.3389/frai.2020.00004",
        "https://sci-hub.se/downloads/2020-04-10/08/emmert-streib2020.pdf"),
    TestCase(
        "10.2307/2620891",
        "testdata/scihub2.html",
        "https://sci-hub.se/10.2307/2620891",
        "https://zero.sci-hub.se/5603/324a0377407b8c56d9d31ea7e9c3561b/savigear1991.pdf"),
]

RESEARCHGATE_CASES = [
    TestCase(
        "10.48550/arXiv.2207.14635",
        "testdata/researchgate0.html",
        "https://www.researchgate.net/publication/362385659_Haptic_Teleoperation_of_High-dimensional_Robotic_Systems_Using_a_Feedback_MPC_Framework",
        'https://researchgate.net/publication/362385659_Haptic_Teleoperation_of_High-dimensional_Robotic_Systems_Using_a_Feedback_MPC_Framework/fulltext/62e760583c0ea87887724795/Haptic-Teleoperation-of-High-dimensional-Robotic-Systems-Using-a-Feedback-MPC-Framework.pdf',
    )
]

EDGE_CASES = [
    TestCase(
        "10.2307/3107006",   # Random doi in the page.
        "testdata/wikipedia_california.html",
        "mock://wikipedia",
        "",  # No pdf_url.
    )
]

# Set this to true to enable live scraping during test.
#
# WARNING:
#   The live test can be relatively slow (~10sec for each fetch), as the external service needs to do fair amount of work, be patient...
#   The live test will cost credits: better use a paid production account.
#
# Even worse, zenrows is not the ultimate silver bullet for web scraping, and there do have times any step can fail:
# 1. The target site returns a blocking page, causing subsequent extraction to fail;
# 2. The target site can return directly a 403 forbidden response, causing WebScrapingError exception to be returned.
#
PERFORM_LIVE_TEST = False

@unittest.skipIf(PERFORM_LIVE_TEST, "Tests skipped due to live scraping...")
@requests_mock.Mocker()
class ResolverTestCase(unittest.TestCase):
    def test_scihub_by_doi(self, m):
        for case in SCIHUB_CASES:
            with open(case.mock_file) as f:
                canned_resp = f.read()
                m.get(case.url, text=canned_resp)

            meta = SciHubResolver.fetch_by_doi(case.doi)
            self.assertEqual({
                'doi': case.doi,
                'pdf_url': case.pdf_url,
            }, meta)

    def test_scihub(self, m):
        for case in SCIHUB_CASES:
            with open(case.mock_file) as f:
                canned_resp = f.read()
                m.get(case.url, text=canned_resp)

            meta = fetch(case.url)
            self.assertEqual({
                'doi': case.doi,
                'pdf_url': case.pdf_url,
            }, meta)

    def test_researchgate(self, m):
        for case in RESEARCHGATE_CASES:
            with open(case.mock_file) as f:
                canned_resp = f.read()
                m.get(case.url, text=canned_resp)

            meta = fetch(case.url)
            self.assertEqual(case.doi, meta['doi'])
            self.assertEqual(case.pdf_url, meta['pdf_url'])

    def test_nonsense_url(self, m):
        for case in EDGE_CASES:
            with open(case.mock_file) as f:
                canned_resp = f.read()
                m.get(case.url, text=canned_resp)

            # Unfortunately we still get one doi from the reference section in the wikipedia document.
            meta = fetch(case.url)
            self.assertEqual(case.doi, meta['doi'])

@unittest.skipIf(not PERFORM_LIVE_TEST, "Live scraping skipped...")
class ResolverLiveTestCase(unittest.TestCase):
    # WARNING(kevin.yang):
    # This is currently my personal account (testing only), replace it with paid production account,
    # as eventually the live scraping will fail eventually due to account exhaustion and/or expiration.
    #
    # PLEASE examine the returned response!
    ZENROWS_PROXY = 'http://c6154c24c2deaad135d9ee29dce0877004d5740f:js_render=true&antibot=true&wait=1000@proxy.zenrows.com:8001'
    ZENROWS_PROXIES = {"http": ZENROWS_PROXY, "https": ZENROWS_PROXY}

    def setUp(self):
        init_zenrows()

    def test_scihub_live(self):
        # NOTE: we need to rotate website urls as otherwise it's possible to trigger DDoS protection.
        case = random.choice(SCIHUB_CASES)
        print(f"Live fetching: {case.url}")
        meta = fetch(case.url, self.ZENROWS_PROXIES, False)
        self.assertEqual(case.doi, meta['doi'])

        # Scihub can sometime returns differnt mirror site, so disable this test.
        #self.assertEqual(case.pdf_url, meta['pdf_url'])

    def test_researchgate_live(self):
        case = random.choice(RESEARCHGATE_CASES)
        print(f"Live fetching {case.url}...")
        meta = fetch(case.url, self.ZENROWS_PROXIES, False)
        self.assertEqual(case.doi, meta['doi'])
        #self.assertEqual(case.pdf_url, meta['pdf_url'])


if __name__ == '__main__':
    unittest.main()