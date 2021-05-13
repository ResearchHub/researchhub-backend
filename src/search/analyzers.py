from elasticsearch_dsl import analyzer


title_analyzer = analyzer(
    'title_analyzer',
    tokenizer='standard',
    filter=[  # Order matters
        'word_delimiter',
        'apostrophe',
        'lowercase',
        'trim',
        'unique'
    ],
    char_filter=['html_strip']
)

shingle_stemmer_analyzer = analyzer(
    'shingle_stemmer_analyzer',
    tokenizer='standard',
    filter=[
        "word_delimiter",
        "stop",
        "apostrophe",
        "lowercase",
        "trim",
        "unique",
        "shingle",
        "stemmer"
    ],
    char_filter=['html_strip']
)
