from topic.models import Topic
from utils.management import OpenAlexLoaderBaseCommand


class Command(OpenAlexLoaderBaseCommand):
    help = "Load Topics from OpenAlex"

    @property
    def model(self):
        return Topic

    @property
    def object_type(self):
        return "topic"
