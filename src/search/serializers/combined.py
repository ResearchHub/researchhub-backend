from rest_framework import serializers

from django.utils.html import strip_tags

from search.serializers import (
    AuthorDocumentSerializer,
    HubDocumentSerializer,
    PaperDocumentSerializer,
    CrossrefPaperSerializer,
    SummaryDocumentSerializer,
    ThreadDocumentSerializer,
    UniversityDocumentSerializer
)


class CombinedSerializer(serializers.BaseSerializer):
    index_serializers = {
        'author': AuthorDocumentSerializer,
        'discussion_thread': ThreadDocumentSerializer,
        'hub': HubDocumentSerializer,
        'paper': PaperDocumentSerializer,
        'crossref_paper': CrossrefPaperSerializer,
        'summary': SummaryDocumentSerializer,
        'university': UniversityDocumentSerializer,
    }

    def __init__(self, *args, **kwargs):
        many = kwargs.pop('many', True)
        super(CombinedSerializer, self).__init__(many=many, *args, **kwargs)

    def to_representation(self, obj):
        return self.get_hit(obj)

    def get_hit(self, obj):
        index_serializers = getattr(self, 'index_serializers')
        if obj.meta.index in index_serializers:
            serializer = index_serializers[obj.meta.index]
            hit = serializer(obj).data
            if hit:
                hit_meta = obj.meta.to_dict()
                if hit_meta['index'] == 'paper':
                    hit_authors = hit['authors']
                    if 'highlight' in hit_meta:
                        if 'authors' in hit_meta['highlight']:
                            meta_authors = hit_meta['highlight']['authors']
                            authors_set = set()
                            for meta_author in meta_authors:
                                cleaned_meta_author = strip_tags(meta_author)
                                authors_set.add(cleaned_meta_author)
                            for hit_author in hit_authors:
                                if hit_author not in authors_set:
                                    hit_meta['highlight']['authors'].append(hit_author)
                                    authors_set.add(hit_author)
                hit['meta'] = hit_meta
        return hit
