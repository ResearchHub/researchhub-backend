from institution.models import Institution
from utils.management import OpenAlexLoaderBaseCommand


class Command(OpenAlexLoaderBaseCommand):
    help = "Load Institutions from OpenAlex"

    @property
    def model(self):
        return Institution

    @property
    def object_type(self):
        return "institution"
