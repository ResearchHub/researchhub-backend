import io
import requests
import pandas as pd

from django.core.management.base import BaseCommand

from user.models import Major


class Command(BaseCommand):
    url = 'https://raw.githubusercontent.com/fivethirtyeight/data/master/college-majors/majors-list.csv'

    def handle(self, *args, **options):
        data = requests.get(self.url).content.decode('utf-8')
        df = pd.read_csv(io.StringIO(data))
        df = df.rename(
            columns={'Major': 'major', 'Major_Category': 'major_category'}
        )

        for i, row in df.iterrows():
            print(i, row)
            row_dict = row.to_dict()
            try:
                Major.objects.create(**row_dict)
            except ValueError:
                pass
