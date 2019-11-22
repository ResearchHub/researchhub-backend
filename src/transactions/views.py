from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Withdrawl
from .serializers import WithdrawlSerializer
class WithdrawlViewset(viewsets.ModelViewSet):
    queryset = Withdrawl.objects.all()
    serializer_class = WithdrawlSerializer
    permission_classes = [IsAuthenticated]
