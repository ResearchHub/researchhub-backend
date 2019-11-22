from django.urls import path

from ethereum.views import address, balance, health, nonce

urlpatterns = [
    path('address/', address, name='address'),
    path('balance/', balance, name='balance'),
    path('nonce/', nonce, name='nonce'),
    path('', health, name='health'),
]
