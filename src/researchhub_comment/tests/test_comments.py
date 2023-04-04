# import decimal
# import time
# from datetime import datetime

# from rest_framework.test import APITestCase

# from discussion.tests.helpers import create_rh_comment
# from paper.tests.helpers import create_paper
# from hub.tests.helpers import create_hub
# from reputation.distributions import Distribution as Dist
# from reputation.distributor import Distributor
# from reputation.models import BountyFee
# from user.models import User
# from user.tests.helpers import create_moderator, create_random_default_user, create_user


# class BountyViewTests(APITestCase):
#     def setUp(self):
#         self.user_1 = create_random_default_user("comment_user_1")
#         self.user_2 = create_random_default_user("comment_user_2")
#         self.user_3 = create_random_default_user("comment_user_3")
#         self.user_4 = create_random_default_user("comment_user_4")
#         self.moderator = create_moderator(first_name="moderator", last_name="moderator")
#         self.paper = create_paper()
#         self.thread = create_rh_comment(created_by=self.recipient)
#         self.thread_response_1 = create_rh_comment(
#             created_by=self.user_2, parent=self.thread
#         )

#     def test_user_can_create_bounty(self, amount=100):
#         self.client.force_authenticate(self.user)

#         create_bounty_res = self.client.post(
#             "/api/bounty/",
#             {
#                 "amount": amount,
#                 "item_content_type": self.thread._meta.model_name,
#                 "item_object_id": self.thread.id,
#             },
#         )

#         self.assertEqual(create_bounty_res.status_code, 201)
#         return create_bounty_res

#     def test_user_can_contribute_to_bounty(self, amount_1=100, amount_2=200):
#         self.client.force_authenticate(self.user)

#         create_bounty_res_1 = self.client.post(
#             "/api/bounty/",
#             {
#                 "amount": amount_1,
#                 "item_content_type": self.thread._meta.model_name,
#                 "item_object_id": self.thread.id,
#             },
#         )

#         self.assertEqual(create_bounty_res_1.status_code, 201)

#         self.client.force_authenticate(self.user_2)
#         create_bounty_res_2 = self.client.post(
#             "/api/bounty/",
#             {
#                 "amount": amount_2,
#                 "item_content_type": self.thread._meta.model_name,
#                 "item_object_id": self.thread.id,
#             },
#         )

#         self.assertEqual(create_bounty_res_2.status_code, 201)
#         return create_bounty_res_1, create_bounty_res_2

#     def test_user_can_create_larger_bounty(self):
#         self.client.force_authenticate(self.user)

#         create_bounty_res = self.client.post(
#             "/api/bounty/",
#             {
#                 "amount": 20000,
#                 "item_content_type": self.thread._meta.model_name,
#                 "item_object_id": self.thread.id,
#             },
#         )

#         self.assertEqual(create_bounty_res.status_code, 201)
#         return create_bounty_res

#     def test_user_can_create_decimal_bounty(self):
#         self.client.force_authenticate(self.user)

#         create_bounty_res = self.client.post(
#             "/api/bounty/",
#             {
#                 "amount": 123.456,
#                 "item_content_type": self.thread._meta.model_name,
#                 "item_object_id": self.thread.id,
#             },
#         )

#         self.assertEqual(create_bounty_res.status_code, 201)

#     def test_user_can_create_long_decimal_bounty(self):
#         self.client.force_authenticate(self.user)

#         create_bounty_res = self.client.post(
#             "/api/bounty/",
#             {
#                 "amount": 123.45679001,
#                 "item_content_type": self.thread._meta.model_name,
#                 "item_object_id": self.thread.id,
#             },
#         )

#         self.assertEqual(create_bounty_res.status_code, 201)
