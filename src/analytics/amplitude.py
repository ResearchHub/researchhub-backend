import requests
import json

from ipware import get_client_ip

from django.contrib.gis.geoip2 import GeoIP2

from researchhub.settings import AMPLITUDE_API_KEY
from user.models import User
from utils.sentry import log_info

geo = GeoIP2()


class Amplitude:
    api_key = AMPLITUDE_API_KEY
    api_url = 'https://api.amplitude.com/2/httpapi'

    def build_hit(self, request, data):
        hit = {}
        event_data = data.copy()

        user_id = data.get('user_id', request.user.id)
        ip, is_routable = get_client_ip(request)

        hit['api_key'] = self.api_key

        if user_id:
            user = User.objects.get(id=user_id)
            user_email = user.email

            invited_by = user.invited_by
            if invited_by:
                invited_by_id = invited_by.id
            else:
                invited_by_id = None

            user_properties = {
                'email': user_email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'reputation': user.reputation,
                'is_suspended': user.is_suspended,
                'probable_spammer': user.probable_spammer,
                'invited_by_id': invited_by_id
            }
            user_id = f'{user_email}_{user_id}'

            if len(user_id) < 5:
                user_id += '_____'
            event_data['user_id'] = user_id
        else:
            user_properties = {
                'email': '',
                'first_name': 'Anonymous',
                'reputation': 0,
                'is_suspended': False,
                'probable_spammer': False
            }
            event_data['user_id'] = '_Anonymous_'

        event_data['user_properties'] = user_properties

        if ip is not None:
            try:
                geo_info = geo.city(ip)
                event_data['ip'] = ip
                event_data['country'] = geo_info['country_name']
                event_data['city'] = geo_info['city']
                event_data['region'] = geo_info['region']
                event_data['dma'] = geo_info['dma_code']
                event_data['location_lat'] = geo_info['latitude']
                event_data['location_lng'] = geo_info['longitude']
            except Exception as e:
                log_info(e)

        hit['events'] = [event_data]
        self.hit = json.dumps(hit)

    def forward_event(self):
        headers = {
          'Content-Type': 'application/json',
          'Accept': '*/*'
        }
        request = requests.post(
            self.api_url,
            data=self.hit,
            headers=headers
        )
        res = request.json()
        if request.status_code != 200:
            log_info(res)

        return res
