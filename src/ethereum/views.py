from rest_framework.decorators import api_view
from rest_framework.response import Response

import ethereum.lib
from ethereum.lib import (
    get_address,
    get_client_version,
    get_nonce
)


@api_view()
def health(request):
    client_version = get_client_version()
    return Response({'client_version': client_version}, status=200)


@api_view()
def address(request):
    address = get_address()
    return Response({'address': address}, status=200)


@api_view()
def balance(request):
    address = request.query_params.get('address', None)
    ticker = request.query_params.get('ticker', '').lower()
    if ticker != '':
        try:
            balance = getattr(ethereum.lib, f'get_{ticker}_balance')(address)
            return Response({'balance': balance}, status=200)
        except AttributeError:
            return Response('No data for the provided ticker', status=200)
        except Exception as e:
            return Response(str(e), status=400)
    else:
        return Response('Missing ticker in request params', status=400)


@api_view()
def nonce(request):
    nonce = get_nonce()
    return Response({'nonce': nonce}, status=200)
