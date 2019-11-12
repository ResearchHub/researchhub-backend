from elasticsearch_dsl import analyzer


title_analyzer = analyzer(
    'title_analyzer',
    tokenizer='standard',
    filter=[  # Order matters
        'word_delimiter',
        'stop',
        'snowball',
        'apostrophe',
        'lowercase'
    ],
    char_filter=['html_strip']
)
