README

A Resolver API is provided in this directory. A resolver can extract PDF metadata from a scraped web page (currently doi and pdf_url). In addition, the PDF content can be downloaded following the extracted pdf_url.

Typically we define a custom Resolver for each literature aggregation website, such as ResearchGate, SciHub, etc.

A custom Resolver needs the following concrete methods:
* `hosts`: returns the list of host variations for the aggregation website;
* `from_doi`: returns the container url for the given literature doi at this site. Note this is NOT always possible;
* `parse`: custom logic to parse the retrieved web page for PDF metadata;

The following global methods are available:
* `<resolver>.fetch_by_doi`: returns the PDF metadata associated with the given doi;
* `fetch`: returns the PDF metadata associated with the given `url`: the first matched resolver will be chosen based on the host from the given `url`;
* `fetch_pdf`: returns the PDF content. The `pdf_url` is included in the metadata by previous call of either `fetch` or `<resolver>.fetch_by_doi`.

Internally we take advantage of an external web-scrapping service (zenrows for now) for the following features:
1. reliability, to bypass Cloudflare;
2. bypass CAPTCHA protection;
3. bypass JavaScript detection and allow the JS in the destination website to be fully executed, mimic the typical browser behavior;

Since the code from this directory is self-contained, feel free to move this package to a new suitable location.

Extra Python packages needed:
* requests-mock: for mocking HTTP requests;
* beautifulsoup4: package for parsing HTML page contents;

----------------------------------- Earlier notes --------------------------------
Research on anti-scraping protection in general:
* Symptom: error 1020 (Access Denied), in the retrieved page content.
* Reason: target website (in this case, researchgate) is protected by cloudflare, and it's cloudflare who detected the scrapping efforts and returned error 1020.

Solution:
* zenrows: paid service (but have trial tier). seems to be working reasonably well (reference: https://app.zenrows.com/builder);
* cloudscraper: won't working for Cloudflare v2 challenge CAPTCHA.
* cfscrape: won't working for reCAPTCHA challengers, no maintenance.

Research on Zotero's PDF content retrieval logic:
Zotero has the concept of PDF resolvers, which defines web scrapping primitives / directives (such as url, HTTP method, HTML tags).

During the resolver's own initialization, it can either form url by contatenation, or consulting a meta-data aggregation sites. Once properly initialized, the resolver can be used for future PDF metadata extraction and PDF retrieval.

Zotero has the following pre-defined resolvers:
1. doi.org resolver:
by design, https://doi.org/{doi} will re-direct to the publisher's container page. However, PDF retrieval is only possible when the user is behind the paywall;

2. OpenAccess resolver:
OpenAccess to return the scraping directive (urls, etc) for the given doi.
In case of Zotero, they use their internal mirror (of Unpaywall) to return the OpenAccess url. OA url (if found) can be scrapped via public internet, however, the hosting site may perform its own anti-scrapping measures.

In addition to the pre-defined resolvers, users can also supply custom resolvers via "extensions.zetero.findPDFs.resolvers" in the Zetero UI.

A popular choice is sci-hub:
sci-hub (https://en.wikipedia.org/wiki/Sci-Hub) is an academic document aggregation site. For example, https://sci-hub.se/10.1109/BioCAS.2015.7348414, will return the literature's container page (along with embedded PDF content), best efforts only.
(Reference: https://gagarine.medium.com/use-sci-hub-with-zotero-as-a-fall-back-pdf-resolver-cf139eb2cea7)
The site also provides meta data query as well, but that's outside the scope for this discussion.

Reference:
1. "this.getPDFResolvers" function from https://github.com/zotero/zotero/blob/6374aea1c8b9d350c5649ef0c0ffbb453a7968a1/chrome/content/zotero/xpcom/attachments.js
