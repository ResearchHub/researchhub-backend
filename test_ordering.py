#!/usr/bin/env python
"""
Test script to reproduce the ordering issue in the List API endpoint.
This script will help verify the current behavior and test our fix.
"""

import os
import sys
import django
from django.conf import settings

# Add the project src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'researchhub.settings')
django.setup()

from django.contrib.auth.models import User
from user_lists.models import List
from user_lists.views import ListViewSet
from django.test import RequestFactory
from rest_framework.test import force_authenticate
import json


def create_test_data():
    """Create test user and lists for testing"""
    # Get or create a test user
    user, created = User.objects.get_or_create(
        username='test_user',
        defaults={'email': 'test@example.com'}
    )
    
    # Clean up existing test lists
    List.objects.filter(created_by=user, name__startswith='Test List').delete()
    
    # Create test lists with different names
    test_lists = [
        'Test List Z',
        'Test List A', 
        'Test List M',
        'Test List B',
    ]
    
    for name in test_lists:
        List.objects.create(name=name, created_by=user)
    
    return user


def test_ordering():
    """Test the ordering behavior of the List API"""
    user = create_test_data()
    factory = RequestFactory()
    view = ListViewSet()
    
    print("Testing List API ordering...")
    print("=" * 50)
    
    # Test 1: No order parameter (should default to name ordering)
    print("Test 1: No order parameter (should be ordered by name)")
    request = factory.get('/api/list/')
    force_authenticate(request, user=user)
    view.request = request
    
    response = view.list(request)
    data = response.data
    
    if isinstance(data, dict) and 'results' in data:
        # Paginated response
        names = [item['name'] for item in data['results'] if item['name'].startswith('Test List')]
    else:
        # Direct response
        names = [item['name'] for item in data if item['name'].startswith('Test List')]
    
    print(f"Returned order: {names}")
    expected_order = ['Test List A', 'Test List B', 'Test List M', 'Test List Z']
    is_correct = names == expected_order
    print(f"Expected order: {expected_order}")
    print(f"Is correctly ordered: {is_correct}")
    print()
    
    # Test 2: Explicit order=name parameter
    print("Test 2: Explicit order=name parameter")
    request = factory.get('/api/list/?order=name')
    force_authenticate(request, user=user)
    view.request = request
    
    response = view.list(request)
    data = response.data
    
    if isinstance(data, dict) and 'results' in data:
        names = [item['name'] for item in data['results'] if item['name'].startswith('Test List')]
    else:
        names = [item['name'] for item in data if item['name'].startswith('Test List')]
    
    print(f"Returned order: {names}")
    is_correct_2 = names == expected_order
    print(f"Expected order: {expected_order}")
    print(f"Is correctly ordered: {is_correct_2}")
    print()
    
    # Test 3: Reverse order
    print("Test 3: Explicit order=-name parameter")
    request = factory.get('/api/list/?order=-name')
    force_authenticate(request, user=user)
    view.request = request
    
    response = view.list(request)
    data = response.data
    
    if isinstance(data, dict) and 'results' in data:
        names = [item['name'] for item in data['results'] if item['name'].startswith('Test List')]
    else:
        names = [item['name'] for item in data if item['name'].startswith('Test List')]
    
    print(f"Returned order: {names}")
    expected_reverse_order = ['Test List Z', 'Test List M', 'Test List B', 'Test List A']
    is_correct_3 = names == expected_reverse_order
    print(f"Expected order: {expected_reverse_order}")
    print(f"Is correctly ordered: {is_correct_3}")
    print()
    
    # Test 4: Check the actual SQL query being generated
    print("Test 4: Checking generated SQL query")
    request = factory.get('/api/list/')
    force_authenticate(request, user=user)
    view.request = request
    
    # Get the queryset that would be used
    qs = view.get_queryset()
    qs = qs.order_by("name")  # Simulate the ordering that should happen
    
    print(f"Generated SQL: {qs.query}")
    print()
    
    return is_correct, is_correct_2, is_correct_3


if __name__ == '__main__':
    try:
        results = test_ordering()
        print("Summary:")
        print(f"Test 1 (no order param): {'PASS' if results[0] else 'FAIL'}")
        print(f"Test 2 (order=name): {'PASS' if results[1] else 'FAIL'}")  
        print(f"Test 3 (order=-name): {'PASS' if results[2] else 'FAIL'}")
        
        if all(results):
            print("\n✅ All tests PASSED - ordering is working correctly!")
        else:
            print("\n❌ Some tests FAILED - ordering issue confirmed")
            
    except Exception as e:
        print(f"Error running tests: {e}")
        import traceback
        traceback.print_exc()
