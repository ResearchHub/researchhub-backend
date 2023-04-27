from elasticsearch_dsl import analyzer, token_filter, tokenizer

delimeter_filter = token_filter(
    "word_delimiter_graph", "word_delimiter", split_on_case_change=False
)

title_analyzer = analyzer(
    "title_analyzer",
    tokenizer="standard",
    filter=[
        delimeter_filter,
        "apostrophe",
        "lowercase",
        "trim",
        "stop",
        "asciifolding",
        "shingle",
        "kstem",
    ],
    char_filter=["html_strip"],
)

content_analyzer = analyzer(
    "content_analyzer",
    tokenizer="standard",
    filter=[
        delimeter_filter,
        "apostrophe",
        "lowercase",
        "kstem",
        "trim",
        "stop",
        "asciifolding",
        "shingle",
    ],
    char_filter=["html_strip"],
)

name_analyzer = analyzer(
    "name_analyzer",
    tokenizer="standard",
    filter=[
        delimeter_filter,
        "apostrophe",
        "lowercase",
        "trim",
        "asciifolding",
        "shingle",
    ],
    char_filter=["html_strip"],
)

whitespace_edge_ngram_analyzer = analyzer(
    "whitespace_edge_ngram_analyzer",
    tokenizer="whitespace",
    filter=[
        "lowercase",
        token_filter("edge_ngram_filter", "edge_ngram", min_gram=1, max_gram=20),
    ],
)

whitespace_edge_ngram_tokenizer = tokenizer(
    "whitespace_edge_ngram_tokenizer",
    type="edge_ngram",
    token_chars=["letter", "digit", "punctuation", "symbol", "whitespace"],
    min_gram=1,
    max_gram=20,
)
