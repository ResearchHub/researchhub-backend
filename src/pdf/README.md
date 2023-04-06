
2 APIs are provided in this directory:
* fetch the PDF content from a url:
Depends on the host for the provided url, certain specialized logic can be applied to extract PDF content;
Optionally, meta data (such as doi) can be returned if possible.

* fetch the PDF content from a known doi:
Can be further specialized for certain well-known aggregation sites;

Both APIs will take advantage of an external reliable web-scrapping service.