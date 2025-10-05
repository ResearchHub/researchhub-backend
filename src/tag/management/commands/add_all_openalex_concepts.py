from tag.models import Concept
from utils.management import OpenAlexLoaderBaseCommand


class Command(OpenAlexLoaderBaseCommand):
    help = "Load Concepts from OpenAlex"

    @property
    def model(self):
        return Concept

    @property
    def object_type(self):
        return "concept"
