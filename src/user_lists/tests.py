from django.test import TestCase
from rest_framework.test import APITestCase


class ModelTests(TestCase):
    def setUp(self):
        pass  # TODO

    # ---------------- BEHAVIOR ----------------

    def test_adding_the_same_document_to_a_list_twice_doesnt_create_duplicates(self):
        pass  # TODO

    def test_two_lists_cant_have_the_same_name_per_user(self):
        pass  # TODO


class APITests(APITestCase):
    def setUp(self):
        pass  # TODO

    # ---------------- PERMISSIONS ----------------

    def test_user_cant_modify_another_users_list(self):
        pass  # TODO

    def test_user_cant_modify_another_users_list_item(self):
        pass  # TODO

    def test_user_cant_delete_another_users_list(self):
        pass  # TODO

    def test_user_cant_delete_another_users_list_item(self):
        pass  # TODO

    def test_user_cant_see_another_users_private_list(self):
        pass  # TODO

    def test_user_can_see_another_users_public_list(self):
        pass  # TODO

    def test_user_cant_create_a_list_for_another_user(self):
        pass  # TODO

    def test_user_cant_create_a_list_item_for_another_user(self):
        pass  # TODO

    # ---------------- PERFORMANCE ----------------

    def test_lists_endpoint_returns_items_with_less_than_n_queries(self):
        pass  # TODO

    # ---------------- BEHAVIOR ----------------

    def test_object_does_not_appear_in_list_after_soft_delete(self):
        pass  # TODO

    def test_list_ordering_by_query_params(self):
        pass  # TODO

    def test_list_item_ordering_by_query_params(self):
        pass  # TODO

    def test_unsupported_document_types_rejected(self):
        pass  # TODO

    def test_invalid_ordering_parameters_return_400(self):
        pass  # TODO

    def test_soft_deleted_lists_not_accessible_via_api(self):
        pass  # TODO
