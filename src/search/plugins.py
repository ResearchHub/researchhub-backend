from django.core.exceptions import ImproperlyConfigured


class IngestPdf:

    def ingest_attachment(self, document):
        index_meta = getattr(document, 'Index')
        if not index_meta:
            message = f'You must declare the Index class inside {document.__name__}'
            raise ElasticSearchPluginError(ImproperlyConfigured, message)

        index = index_meta.name
        self._add_to_pipeline_if_not_exists()
        # get document id
        # make an ingest cal
        index = document.index
        url = f'{index}/_doc/{document.id}?pipeline=attachment'
        client.put(url)

    def _add_to_pipeline_if_not_exists(self):
        if self._check_exists() is False:
            try:
                self._add_to_pipeline()
            except Exception as e:
                print(e)

    def _add_to_pipeline(self):
        description = 'Extract pdf attachment'
        data = {
            'description': description,
            'processors': [
                {
                    'attachment': {
                        'field': 'pdf'
                    }
                }
            ]
        }
        url = '_ingest/pipeline/attachment'
        response = client.put(url, data, content_type='application/json')
        if (response.message != 'OK'):
            raise ElasticSearchPluginError('Failed to add to pipeline')
