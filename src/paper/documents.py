from django_elasticsearch_dsl import Document, fields as es_fields
from django_elasticsearch_dsl.registries import registry

from .models import Paper
from user.models import Author


@registry.register_document
class PaperDocument(Document):
    # authors = fields.ObjectField(properties={
    #     'first_name': fields.TextField(),
    #     'last_name': fields.TextField(),
    #     'university': fields.IntegerField(),
    # })

    class Index:
        name = 'papers'
        settings = {
            'number_of_shards': 1,
            'number_of_replicas': 0,
        }

    class Django:
        model = Paper
        fields = [
            'title',
            'doi',
            'tagline',
            'publication_type',
        ]
        related_models = [Author]

        # Ignore auto updating of Elasticsearch when a model is saved
        # or deleted:
        # ignore_signals = True

        # Don't perform an index refresh after every update (overrides global
        # setting):
        # auto_refresh = False

        # Paginate the django queryset used to populate the index with the
        # specified size (by default it uses the database driver's default
        # setting)
        # queryset_pagination = 5000

    # def get_queryset(self):
    #     """Not mandatory but to improve performance we can select related in one sql request"""
    #     return super(PaperDocument, self).get_queryset().select_related(
    #         'authors'
    #     )

    # def get_instances_from_related(self, related_instance):
    #     """If related_models is set, define how to retrieve the Car instance(s) from the related model.
    #     The related_models option should be used with caution because it can lead in the index
    #     to the updating of a lot of items.
    #     """
    #     if isinstance(related_instance, Author):
    #         return related_instance.car_set.all()
    #     elif isinstance(related_instance, Hub):
    #         return related_instance.car
