# Feed

## Elasticsearch

### Rebuild Index

To rebuild the feed entries index, use the following command:

```sh
python manage.py search_index --rebuild --models feed.FeedEntry
```