### Elasticsearch server

```
curl --request GET \
  --url http://localhost:9200/
```

health
```
curl --request GET \
  --url 'http://localhost:9200/_cat/health?v=&pretty='
```

indices
```
curl --request GET \
  --url 'http://localhost:9200/_cat/indices?v=' \
  --header 'content-type: application/json'
```

create document
```
curl --request PUT \
  --url 'http://localhost:9200/papers/_doc/1?pretty=' \
  --header 'content-type: application/json' \
  --data '{
  "title": "John Doe"
}'
```

get document
```
curl --request GET \
  --url http://localhost:9200/papers/_doc/1
```

get all documents
```
curl --request GET \
  --url http://localhost:9200/papers/_search \
  --header 'content-type: application/json' \
  --data '{
	"query": { "match_all": {} }
}'
```

search
```
curl --request GET \
  --url http://localhost:9200/papers/_search \
  --header 'content-type: application/json' \
  --data '{
	"query": { "match": {"title": "Lattice crypto"} }
}'
```

### Django server

get all documents
```
curl --request GET \
  --url http://localhost:8000/api/search/papers/ \
  --header 'authorization: Token <auth_token>'
```

partial search
```
curl --request GET \
  --url 'http://localhost:8000/api/search/papers/?title__contains=attice' \
  --header 'authorization: Token <auth_token>'
```

keyword search
```
curl --request GET \
  --url 'http://localhost:8000/api/search/papers/?search=Lattice' \
  --header 'authorization: Token <auth_token>
```

suggestions - completion
```
curl --request GET \
  --url 'http://localhost:8000/api/search/papers/suggest/?title_suggest__completion=d' \
  --header 'authorization: Token <auth_token>' \
```

suggestions - phrase
```
curl --request GET \
  --url 'http://localhost:8000/api/search/papers/suggest/?title_suggest__phrase=dumm' \
  --header 'authorization: Token <auth_token>' \
```

suggestions - term
```
curl --request GET \
  --url 'http://localhost:8000/api/search/papers/suggest/?title_suggest__term=dumm' \
  --header 'authorization: Token <auth_token>' \
```
