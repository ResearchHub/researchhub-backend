from django.core.exceptions import ImproperlyConfigured
from elasticsearch import NotFoundError
from elasticsearch_dsl import Search
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet


class ElasticsearchViewSet(GenericViewSet):
    """
    Base ViewSet for Elasticsearch document views.
    Replaces django_elasticsearch_dsl_drf.viewsets.DocumentViewSet
    """

    document = None
    serializer_class = None
    lookup_field = "id"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.document:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} must define a document attribute"
            )

    def get_queryset(self):
        """
        Get the Elasticsearch search instance.
        """
        return self.document.search()

    def get_object(self):
        """
        Retrieve a single document instance.
        """
        lookup_value = self.kwargs.get(self.lookup_field)

        try:
            # Get the document by ID
            document = self.document.get(id=lookup_value)
            return document
        except NotFoundError:
            # Return None to trigger 404
            return None

    def list(self, request, *args, **kwargs):
        """
        List documents with filtering, searching, and pagination.
        """
        queryset = self.filter_queryset(self.get_queryset())

        # Check if this is a suggestion request (django-elasticsearch-dsl-drf compatibility)
        # Look for any parameter ending with __completion
        is_suggest_request = any(
            param.endswith("__completion") for param in request.query_params.keys()
        )

        if is_suggest_request:
            # Execute the query and return suggestions
            response = queryset.execute()

            # Find which __completion parameter was used
            completion_param = None
            for param in request.query_params.keys():
                if param.endswith("__completion"):
                    completion_param = param
                    break

            # Extract suggestions from response
            if hasattr(response, "suggest") and response.suggest:
                suggest_dict = response.suggest.to_dict()

                # Format response to match django-elasticsearch-dsl-drf exactly
                formatted_response = {}

                for suggest_name, suggest_data in suggest_dict.items():
                    # Use the __completion parameter name as the key
                    response_key = completion_param or f"{suggest_name}__completion"
                    formatted_suggestions = []

                    for suggestion in suggest_data:
                        # Get the query text that was used
                        query_text = request.query_params.get(completion_param, "")

                        # Format each suggestion group
                        suggestion_group = {
                            "text": suggestion.get("text", query_text),
                            "offset": suggestion.get("offset", 0),
                            "length": suggestion.get("length", len(query_text)),
                            "options": [],
                        }

                        # Format each option
                        for option in suggestion.get("options", []):
                            formatted_option = {
                                "text": option.get("text", ""),
                                "_score": option.get("_score", 0),
                                "_source": option.get("_source", {}),
                            }

                            # Add index metadata if available
                            if "_index" in option:
                                formatted_option["_index"] = option["_index"]
                            if "_type" in option:
                                formatted_option["_type"] = option["_type"]
                            if "_id" in option:
                                formatted_option["_id"] = option["_id"]

                            suggestion_group["options"].append(formatted_option)

                        formatted_suggestions.append(suggestion_group)

                    formatted_response[response_key] = formatted_suggestions

                return Response(formatted_response)

            # If no suggestions, return empty response with the right key
            response_key = completion_param or "suggestions"
            return Response({response_key: []})

        # Regular list request
        # Apply pagination
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        # Execute search and serialize results
        response = queryset.execute()
        serializer = self.get_serializer(response, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a single document.
        """
        instance = self.get_object()
        if instance is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def filter_queryset(self, queryset):
        """
        Apply filtering backends to the queryset.
        """
        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(
                request=self.request, queryset=queryset, view=self
            )
        return queryset

    @property
    def paginator(self):
        """
        The paginator instance associated with the view, or `None`.
        """
        if not hasattr(self, "_paginator"):
            if self.pagination_class is None:
                self._paginator = None
            else:
                self._paginator = self.pagination_class()
        return self._paginator

    def paginate_queryset(self, queryset):
        """
        Return a single page of results, or `None` if pagination is disabled.
        """
        if self.paginator is None:
            return None
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        """
        Return a paginated style `Response` object for the given output data.
        """
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data)
