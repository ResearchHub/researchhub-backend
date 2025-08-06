"""
Overriding django-elasticsearch-dsl-drf multi match query backend
in order to support RH's use case. Changes highlighted below.
"""

import copy

from elasticsearch_dsl import Q

from search.base.query_backends import BaseSearchQueryBackend


class MultiMatchQueryBackend(BaseSearchQueryBackend):

    query_type = "multi_match"

    """
    Perform prefix phrase match if greater than or equal to length specified.
    """
    min_len_for_phrase_match_query = 6
    """
    Add additional weight to exact matches
    """
    boost_for_phrase_query = 2
    """
    If score_field is specified on view, control how much weight the field should have
    """
    factor_for_function_score = 1.4

    @classmethod
    def get_field(cls, field, options):
        """Get field.

        :param field:
        :param options:
        :return:
        """
        if not options:
            options = {}

        field_name = options["field"] if "field" in options else field

        if "boost" in options:
            return "{}^{}".format(field_name, options["boost"])
        return field_name

    @classmethod
    def get_query_options(cls, request, view, search_backend):
        query_options = getattr(view, "multi_match_options", {})

        return query_options

    @classmethod
    def construct_query(cls, request, view, query_fields, search_term, query_opts):
        score_field = None
        try:
            score_field = getattr(view, "score_field")
        except:
            pass

        if score_field is not None:
            return Q(
                "function_score",
                query={
                    "multi_match": {
                        "query": search_term,
                        "fields": query_fields,
                        **query_opts,
                    }
                },
                field_value_factor={
                    "field": score_field,
                    "factor": cls.factor_for_function_score,
                    "modifier": "sqrt",
                    "missing": 1,
                },
            )
        else:
            return Q(
                cls.query_type, query=search_term, fields=query_fields, **query_opts
            )

    @classmethod
    def construct_phrase_query(
        cls, request, view, query_fields, search_term, query_opts
    ):
        phrase_query_opts = copy.deepcopy(query_opts)
        phrase_query_opts["type"] = "phrase_prefix"
        phrase_query_opts["boost"] = cls.boost_for_phrase_query

        # Fuzziness not allowed in phrases
        if "fuzziness" in phrase_query_opts:
            del phrase_query_opts["fuzziness"]

        return cls.construct_query(
            request, view, query_fields, search_term, phrase_query_opts
        )

    @classmethod
    def construct_complex_query(
        cls, request, view, field, search_term, query_opts, field_opts
    ):
        complex_query_opts = {**copy.deepcopy(query_opts), **field_opts}
        return cls.construct_query(
            request, view, [field], search_term, complex_query_opts
        )

    """
    Returns all fields that do not have "options" key
    specified on a per-field basis.
    """

    @classmethod
    def get_simple_search_fields(cls, query_fields):
        simple_fields = {}
        for field in query_fields:
            if "options" not in query_fields[field]:
                simple_fields[field] = query_fields[field]

        return simple_fields

    """
    Returns all fields that have "options" key
    specified on per-field basis.
    """

    @classmethod
    def get_complex_search_fields(cls, query_fields):
        complex_fields = []
        for field in query_fields:
            if "options" in query_fields[field]:
                if "condition" in query_fields[field]:
                    f = (
                        field,
                        query_fields[field]["options"],
                        query_fields[field]["condition"],
                    )
                else:
                    f = (field, query_fields[field]["options"], None)

                complex_fields.append(f)

        return complex_fields

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
        if hasattr(view, "multi_match_search_fields"):
            view_search_fields = copy.deepcopy(
                getattr(view, "multi_match_search_fields")
            )
        else:
            view_search_fields = copy.deepcopy(view.search_fields)

        simple_fields = cls.get_simple_search_fields(view_search_fields)
        complex_fields = cls.get_complex_search_fields(view_search_fields)

        __is_complex = isinstance(simple_fields, dict)

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
                fields = search_backend.split_lookup_complex_multiple_value(_field)
                for field in fields:
                    if field in simple_fields:
                        if __is_complex:
                            query_fields.append(
                                cls.get_field(field, simple_fields[field])
                            )
                        else:
                            query_fields.append(field)

            # If it's just a simple search like
            # /search/books/?search_multi_match=lorem ipsum
            # Fields shall be defined in a very simple way.
            else:
                # It's a dict, see example 1 (complex)
                if __is_complex:
                    for field, options in simple_fields.items():
                        query_fields.append(cls.get_field(field, options))

                # It's a list, see example 2 (simple)
                else:
                    query_fields = copy.deepcopy(simple_fields)

            query_opts = cls.get_query_options(request, view, search_backend)
            q = cls.construct_query(
                request, view, query_fields, __search_term, query_opts
            )
            __queries.append(q)

            """
            Complex fields are ones that have "options" key
            specified. One additional query will be performed for each field
            that inclues "options". The use case here is needing to override the
            global options on a per-field basis (e.g. analyzer on one field different than globally specified analyzer)
            """
            for field_tuple in complex_fields:
                field, field_opts, condition = field_tuple
                complex_q = cls.construct_complex_query(
                    request, view, field, __search_term, query_opts, field_opts
                )

                if condition is None or (
                    callable(condition) and condition(search_term)
                ):
                    __queries.append(complex_q)

            """
            Perform an additional phrase prefix boosted query
            the goal of which is to boost exact phrases requested.
            """
            if len(__search_term) >= cls.min_len_for_phrase_match_query:
                phrase_q = cls.construct_phrase_query(
                    request, view, query_fields, __search_term, query_opts
                )
                __queries.append(phrase_q)

        return __queries

    def filter(self, queryset, query_string, fields=None, options=None):
        """
        Apply multi-match query to queryset.
        """

        # Create a mock request and view to work with existing logic
        class MockRequest:
            def __init__(self, query_string):
                self.query_params = {"search_multi_match": query_string}

        class MockView:
            def __init__(self, fields):
                self.search_fields = fields
                self.multi_match_search_fields = fields

        class MockBackend:
            @staticmethod
            def get_search_query_params(request):
                return [request.query_params.get("search_multi_match", "")]

            @staticmethod
            def split_lookup_name(value, maxsplit=-1):
                return [value]

            @staticmethod
            def split_lookup_complex_multiple_value(value):
                return value.split(",")

        request = MockRequest(query_string)
        view = MockView(fields or {})
        search_backend = MockBackend()

        queries = self.construct_search(request, view, search_backend)

        if queries:
            combined_query = queries[0]
            for query in queries[1:]:
                combined_query = combined_query | query
            return queryset.query(combined_query)

        return queryset
