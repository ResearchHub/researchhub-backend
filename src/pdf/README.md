README

A Resolver API is provided in this directory.

In general, a custom Resolver need to define the following API methods:
* `hosts`: returns the list of host for this particular Resolver subclass;
* `from_doi`: returns the container url for the given doi;
* `parse`: custom logic to parse the retrieved web page for PDF metadata;

The APIs will take advantage of an external reliable web-scrapping service (zenrows for now).

The following global methods are available:
* `<resolver>.fetch_by_doi`: returns the PDF metadata associated with the given doi;
* `fetch`: returns the PDF metadata associated with the given url;
* `fetch_pdf`: returns the PDF content. The pdf_url should be retrieved from previous metadata, as returned by either `fetch` or `<resolver>.fetch_by_doi`.

Extra Python packages:
* requests-mock: for mocking HTTP requests;
* beautifulsoup: package for parsing HTML page contents;