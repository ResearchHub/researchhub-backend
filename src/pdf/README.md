# README

A Resolver API is provided in this directory.

From a high level point of view, a resolver can extract PDF metadata from a scraped web page (currently `doi` and `pdf_url`). In addition, the PDF content can be downloaded following the extracted `pdf_url`.

So it's obvious the work here will cover 2 parts:
* reliably retrieve the content from a remote web page;
* reliably extract the meta data from the page content.

## Web scraping

These are a few considerations for modern web design:
1. A modern dynamic web page typically has Javascript code that will be executed after the page is loaded. Without a JS execution engine, the web page rendering won't be complete even if we get all the static content;
2. the website can inspect the incoming `Agent` identifier and respond differently: a web scraping library can somehow fake this, but it's kind of unreliable, expecially when all requests come from the same IP in a short burst;
3. A website can issue CAPTCHA challenge for suspecious users, and this is true especially for those serving valuable contents;
4. More generally, a website can employ service such as Cloudflare to detect suspecious activities (DDoS attack), and will block access if, for example, too many requests from the same set of IP pools.

If we use Python's `requests` package naively (even fake the `Agent`), to scrape `researchgate`, for example, we will see `error 1020 (Access Denied)` in the retrieved page content. It implies the target website (`researchgate`) is protected by Cloudflare, and it's Cloudflare who detected the scrapping efforts and returned error 1020.

We can either try to solve these issues by ourselves (which can be quite tricky to get right), or use an external web-scrapping service. For this reason, I've researched:
* zenrows: paid service (but have trial tier): seems to be working reasonably well (reference: https://app.zenrows.com/builder);
* cloudscraper: won't working for Cloudflare v2 challenge CAPTCHA.
* cfscrape: won't working for reCAPTCHA challengers, no maintenance.

I've decided to use `zenrows` for now, with the following benefits:
1. have its own JavaScript engine to ensure the target web content is fully rendered, after initial fetch;
2. bypass CAPTCHA protection;
3. reliability bypass Cloudflare (or similar services);

At the end of the day, we will get the full content of the target web site, for a small fee.

## Page extraction

Once we have the full content of a web site, the next task is to extract proper metadata from the web page, which can be achieved by Resolver APIs. Typically we define a custom Resolver for each literature aggregation website, such as ResearchGate, SciHub, etc.

A custom Resolver needs the following concrete methods:
* `hosts`: returns the list of host variations for the aggregation website;
* `from_doi`: returns the container url for the given `doi` at this aggregation site: note this is NOT always possible, when there is no obvious mapping;
* `parse`: custom logic to parse the retrieved web page for PDF metadata;

The following global methods are available:
* `<resolver>.fetch_by_doi`: returns the PDF metadata associated with the given `doi`;
* `fetch`: returns the PDF metadata associated with the given `url`: the first matched resolver will be chosen based on the host from the given `url`;
* `fetch_pdf`: returns the PDF content. The `pdf_url` is included in the metadata by previous call of either `fetch` or `<resolver>.fetch_by_doi`.

Since the code from this directory is self-contained, feel free to move this package to a new suitable location.

## Misc

Extra Python packages needed:
* requests-mock: for mocking HTTP requests;
* beautifulsoup4: package for parsing HTML page contents;

## Previous research notes

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
