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