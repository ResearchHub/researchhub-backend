import requests

from ipware import get_client_ip

from django.contrib.gis.geoip2 import GeoIP2

from researchhub.settings import AMPLITUDE_API_KEY
from user.models import User


class Amplitude:
    api_key = AMPLITUDE_API_KEY
    api_url = 'https://api.amplitude.com/2/httpapi'

    def build_hit(self, request, data):
        hit = data.copy()
        user_id = data['user_id']
        user = User.objects.get(id=user_id)

        ip, is_routable = get_client_ip(request)

        user_properties = {
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'reputation': user.reputation,
        }

        hit['user_properties'] = user_properties

        if ip is not None:
            geo = GeoIP2()
            geo_info = geo.city(ip)
            hit['ip'] = ip
            hit['country'] = geo_info['country_name']
            hit['city'] = geo_info['city']
            hit['region'] = geo_info['region']
            hit['dma'] = geo_info['dma_code']
            hit['location_lat'] = geo_info['latitude']
            hit['location_lon'] = geo_info['longitude']

        self.hit = hit

    def forward_event(self):
        headers = {
          'Content-Type': 'application/json',
          'Accept': '*/*'
        }
        response = requests.post(
            self.api_url,
            data=self.hit,
            headers=headers
        )
        return response.json()
