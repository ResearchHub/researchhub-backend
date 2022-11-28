import json

import requests
from django.core.management.base import BaseCommand

from analytics.amplitude import Amplitude
from researchhub.settings import AMPLITUDE_API_KEY
from user.models import User

API_URL = "https://api.amplitude.com/2/httpapi"


class Command(BaseCommand):
    def get_user_props(self, user, user_email):
        # Makes one less db call if user email is passed in
        user_properties = {
            "is_suspended": user.is_suspended,
            "probable_spammer": user.probable_spammer,
        }
        return user_properties

    def forward_amp_event(self, events):
        event_data = {"api_key": AMPLITUDE_API_KEY, "events": events}
        data = json.dumps(event_data)
        headers = {"Content-Type": "application/json", "Accept": "*/*"}
        request = requests.post(API_URL, data=data, headers=headers)
        res = request.json()
        if request.status_code != 200:
            res = request.json()
            print(res)
        print(res)

    def update_users(self, users):
        print("Users")
        count = users.count()
        events = []
        amp = Amplitude()
        for i, user in enumerate(users.iterator()):
            if (i % 1000 == 0 and i != 0) or (count - 1) == i:
                self.forward_amp_event(events)
                events = []
            else:
                print(f"{i}/{count}")
                user_email = user.email
                user_id, user_props = amp._build_user_properties(user)
                hit = {
                    "user_id": user_id,
                    "event_type": "update_user",
                    "user_properties": user_props,
                }
                events.append(hit)

    def handle(self, *args, **options):
        users = User.objects.filter(first_name__icontains="student")
        self.update_users(users)
