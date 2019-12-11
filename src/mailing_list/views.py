from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.views import Response

from mailing_list.models import EmailAddress
from mailing_list.serializers import EmailAddressSerializer


class MailingListViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = EmailAddress.objects.all()
    serializer_class = EmailAddressSerializer
    permission_classes = [AllowAny]

    @action(
        detail=False,
        methods=['POST'],
    )
    def update_or_create_email_preference(self, request):
        address = request.data['email']
        is_opted_out = request.data['opt_out']

        email_address, created = EmailAddress.objects.get_or_create(
            address=address
        )
        email_address.set_opt_out(is_opted_out)

        serialized = EmailAddressSerializer(email_address)

        status = 200
        if created:
            status = 201

        return Response(serialized.data, status=status)
