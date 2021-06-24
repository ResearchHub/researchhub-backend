from elasticsearch_dsl import analyzer, tokenizer

title_analyzer = analyzer(
    "title_analyzer",
    tokenizer="standard",
    filter=[
        "word_delimiter",
        "apostrophe",
        "lowercase",
        "trim",
        "stop",
        "asciifolding",
        "shingle",
        "stemmer",
    ],
    char_filter=["html_strip"]
)

content_analyzer = analyzer(
    "content_analyzer",
    tokenizer="standard",
    filter=[
        "word_delimiter",
        "apostrophe",
        "lowercase",
        "stemmer",
        "trim",
        "stop",
        "asciifolding",
        "shingle",
    ],
    char_filter=["html_strip"]
)

name_analyzer = analyzer(
    "name_analyzer",
    tokenizer="standard",
    filter=[
        "word_delimiter",
        "apostrophe",
        "lowercase",
        "trim",
        "asciifolding",
        "shingle",
    ],
    char_filter=["html_strip"]
)