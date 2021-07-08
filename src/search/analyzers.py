from elasticsearch_dsl import analyzer, tokenizer, token_filter

delimeter_filter = token_filter(
    'word_delimiter_graph',
    'word_delimiter',
    split_on_case_change=False
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
    char_filter=["html_strip"]
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
    char_filter=["html_strip"]
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
    char_filter=["html_strip"]
)