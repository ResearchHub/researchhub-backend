# views.py

import requests
from django.http import HttpResponse, StreamingHttpResponse
from urllib.parse import urlparse
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError

def is_valid_url(url):
    try:
        URLValidator()(url)
        parsed_url = urlparse(url)
        return parsed_url.scheme in ('http', 'https')
    except ValidationError:
        return False
    
ALLOWED_CONTENT_TYPES = ['application/pdf']

def proxy_view(request):
    # Get the URL from request parameters (e.g., /proxy/?url=http://example.com/file.pdf)
    url = request.GET.get('url')
    if not url or not is_valid_url(url):
        return HttpResponse('Invalid or disallowed URL.', status=400)

    try:
        response = requests.get(url, stream=True, timeout=10)

        # Check if the content type is allowed
        content_type = response.headers.get('Content-Type')
        if content_type not in ALLOWED_CONTENT_TYPES:
            return HttpResponse('Disallowed content type.', status=403)

        # Forward the content type and disposition headers
        content_type = response.headers.get('Content-Type')
        content_disposition = response.headers.get('Content-Disposition')

        # Stream the response back to the frontend
        # StreamingHttpResponse helps to avoid loading the entire response into memory
        # This is useful for large files.
        django_response = StreamingHttpResponse(
            streaming_content=(chunk for chunk in response.iter_content(4096)),
            content_type=content_type
        )
        if content_disposition:
            django_response['Content-Disposition'] = content_disposition

        return django_response
    except requests.Timeout:
        return HttpResponse('Request timed out.', status=504)
    except requests.RequestException as e:
        return HttpResponse(f'Failed to fetch the document: {e}', status=500)
