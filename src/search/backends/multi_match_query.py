"""
Overriding django-elasticsearch-dsl-drf multi match query backend 
in order to support RH's use case. Changes highlighted below.
"""

from django_elasticsearch_dsl_drf.filter_backends.search.query_backends import BaseSearchQueryBackend
from elasticsearch_dsl import query, Q
import copy


class MultiMatchQueryBackend(BaseSearchQueryBackend):

    query_type = 'multi_match'

    """
    Perform prefix phrase match if greater than or equal to length specified.
    """
    min_len_for_phrase_match_query = 6

    @classmethod
    def get_field(cls, field, options):
        """Get field.

        :param field:
        :param options:
        :return:
        """
        if not options:
            options = {}

        field_name = options['field'] \
            if 'field' in options \
            else field

        if 'boost' in options:
            return '{}^{}'.format(field_name, options['boost'])
        return field_name


    @classmethod
    def get_query_options(cls, request, view, search_backend):
        query_options = getattr(view, 'multi_match_options', {})

        return query_options

    @classmethod
    def construct_search(cls, request, view, search_backend):
        """Construct search.

        In case of multi match, we always look in a group of fields.
        Thus, matching per field is no longer valid use case here. However,
        we might want to have multiple fields enabled for multi match per
        view set, and only search in some of them in specific request.

        Example:

            /search/books/?search_multi_match=lorem ipsum
            /search/books/?search_multi_match=title,summary:lorem ipsum

        Note, that multiple searches are not supported (would not raise
        an exception, but would simply take only the first):

            /search/books/?search_multi_match=title,summary:lorem ipsum
                &search_multi_match=author,publisher=o'reily

        In the view-set fields shall be defined in a very simple way. The
        only accepted argument would be boost (per field).

        Example 1 (complex):

            multi_match_search_fields = {
                'title': {'field': 'title.english', 'boost': 4},
                'summary': {'boost': 2},
                'description': None,
            }

        Example 2 (simple list):

            multi_match_search_fields = (
                'title',
                'summary',
                'description',
            )


        :param request:
        :param view:
        :param search_backend:
        :return:
        """
        if hasattr(view, 'multi_match_search_fields'):
            view_search_fields = copy.deepcopy(
                getattr(view, 'multi_match_search_fields')
            )
        else:
            view_search_fields = copy.deepcopy(view.search_fields)

        __is_complex = isinstance(view_search_fields, dict)

        # Getting the list of search query params.
        query_params = search_backend.get_search_query_params(request)

        __queries = []
        for search_term in query_params[:1]:
            __values = search_backend.split_lookup_name(search_term, 1)
            __len_values = len(__values)
            __search_term = search_term

            query_fields = []

            # If we're dealing with case like
            # /search/books/?search_multi_match=title,summary:lorem ipsum
            if __len_values > 1:
                _field, value = __values
                __search_term = value
                fields = search_backend.split_lookup_complex_multiple_value(
                    _field
                )
                for field in fields:
                    if field in view_search_fields:
                        if __is_complex:
                            query_fields.append(
                                cls.get_field(field, view_search_fields[field])
                            )
                        else:
                            query_fields.append(field)

            # If it's just a simple search like
            # /search/books/?search_multi_match=lorem ipsum
            # Fields shall be defined in a very simple way.
            else:
                # It's a dict, see example 1 (complex)
                if __is_complex:
                    for field, options in view_search_fields.items():
                        query_fields.append(
                            cls.get_field(field, options)
                        )

                # It's a list, see example 2 (simple)
                else:
                    query_fields = copy.deepcopy(view_search_fields)


            query_opts = cls.get_query_options(request, view, search_backend)


            score_field = None
            try:
                score_field = getattr(view, 'score_field')    
            except:
                pass
            
            if score_field is not None:
                __queries.append(
                    Q(
                        'function_score',
                        query={
                            'multi_match': {
                                'query': __search_term,
                                'fields': query_fields,
                                **query_opts

                            }
                        },
                        functions=[
                            query.SF(
                                'script_score',
                                script={
                                    'lang': 'painless',
                                    'inline': "if (doc.containsKey('" + score_field + "')) { return doc.get('" + score_field + "').value + _score; } else { return _score }"
                                }
                            )
                        ]

                    )
                )
            else:
                __queries.append(
                    Q(
                        cls.query_type,
                        query=__search_term,
                        fields=query_fields,
                        **query_opts
                    )
                )

            """
            Perform an additional phrase prefix boosted query
            the goal of which is to boost exact phrases requested.
            """
            if len(__search_term) >= cls.min_len_for_phrase_match_query:
                phrase_query_opts = copy.deepcopy(query_opts)
                phrase_query_opts['type'] = 'phrase_prefix'
                phrase_query_opts['boost'] = 2
              
                if 'fuzziness' in phrase_query_opts:                
                    del phrase_query_opts['fuzziness']

                    __queries.append(
                        Q(
                            cls.query_type,
                            query=__search_term,
                            fields=query_fields,
                            **phrase_query_opts
                        )
                    )

        return __queries

