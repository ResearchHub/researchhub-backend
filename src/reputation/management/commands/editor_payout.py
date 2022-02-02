'''
Creates a wallet for users
'''

import time
import pandas as pd

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from researchhub_access_group.constants import EDITOR

from reputation.distributor import Distributor
from reputation.distributions import Distribution as dist
from user.models import User
from hub.models import Hub

class Command(BaseCommand):

    def handle(self, *args, **options):
        df = pd.read_csv('editor_payout_jan_2022.csv')

        write_df = pd.DataFrame({'user_id': [], 'email': [], 'payout': []})

        all_editors = editor_qs = User.objects.filter(
            permissions__isnull=False,
            permissions__access_type=EDITOR,
            permissions__content_type=ContentType.objects.get_for_model(Hub)
        ).distinct()

        distributed_editors = {}

        for i, row in df.iterrows():
            email = row['Email']
            distributed_editors[email.lower()] = True
            amount = row['Total RSC payout']
            # amount = amt
            try:
                user = User.objects.get(email__iexact=email)
                distributor = Distributor(
                    dist('EDITOR_PAYOUT', amount, False),
                    user,
                    None,
                    time.time()
                )

                df2 = {'user_id': distributor.recipient.id, 'email': distributor.recipient.email, 'payout': distributor.distribution.amount}
                write_df = write_df.append(df2, ignore_index=True)
                write_df['user_id'] = write_df['user_id'].astype(int)
            except Exception as e:
                print(e)
                print(email)
        
        for editor in all_editors:
            if distributed_editors.get(editor.email):
                continue
            else:
                AMOUNT = 90909.1
                distributor = Distributor(
                    dist('EDITOR_PAYOUT', AMOUNT, False),
                    editor,
                    None,
                    time.time()
                )

                df2 = {'user_id': distributor.recipient.id, 'email': distributor.recipient.email, 'payout': distributor.distribution.amount}
                write_df = write_df.append(df2, ignore_index=True)
                write_df['user_id'] = write_df['user_id'].astype(int)
        
        write_df.to_csv('jan_editor_payout_calc.csv')
            # if distribute:
            #     distribution = distributor.distribute()