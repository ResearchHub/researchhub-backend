import datetime
import math
from researchhub_document.related_models.constants.document_type import PAPER
import numpy as np

class HotScoreMixin:
  def _c(self, num):
      if num >= 1:
          return 1
      elif num == 0:
          return 0
      else:
          return -1

  def _count_comment_votes(self, doc):
    vote_total = 0
    for t in doc.threads.filter(is_removed=False).iterator():

      print(t.votes[0].__dict__)

    return vote_total

  def calculate_hot_score_v2(self, should_save=False):
    hot_score = 0
    doc = self.get_document()