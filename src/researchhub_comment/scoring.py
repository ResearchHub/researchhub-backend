import math
import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional

from django.db.models import Sum, DecimalField
from django.db.models.functions import Cast
from django.utils import timezone

from purchase.models import Purchase
from reputation.models import BountySolution


class ScoringConfig:
    HALF_LIFE_DAYS = 30
    VERIFICATION_MULTIPLIER = 3.0
    LOG_BASE_MULTIPLIER = 10
    QUALITY_PENALTY = 0.1
    MIN_WORD_COUNT = 5
    MIN_CHAR_COUNT = 20
    SECONDS_PER_DAY = 86400
    DECAY_BASE = 0.5


class CommentQualityFilter:
    config = ScoringConfig()
    SPAM_PATTERNS = [
        re.compile(r'^(test|testing|test\d+)$', re.IGNORECASE),
        re.compile(r'^[.!?\s]+$', re.IGNORECASE),
        re.compile(r'^(asdf|qwer|zxcv)+$', re.IGNORECASE),
        re.compile(r'^first!?$', re.IGNORECASE),
        re.compile(r'^x{3,}$', re.IGNORECASE)
    ]
    
    @classmethod
    def is_low_quality(cls, comment) -> bool:
        if not hasattr(comment, 'comment_content_json'):
            return False
            
        content = getattr(comment, 'plain_text', '')
        
        if len(content) < cls.config.MIN_CHAR_COUNT:
            return True
            
        word_count = len(content.split())
        if word_count < cls.config.MIN_WORD_COUNT:
            return True
            
        for pattern in cls.SPAM_PATTERNS:
            if pattern.match(content.strip()):
                return True
                
        return False
    
    
    @classmethod
    def apply_quality_penalty(cls, score: float, comment) -> float:
        if cls.is_low_quality(comment):
            return score * cls.config.QUALITY_PENALTY
        return score


class CommentScorer:
    config = ScoringConfig()
    
    @classmethod
    def calculate_score(cls, comment, annotated_data=None) -> Dict[str, float]:
        log_upvotes = cls._calculate_log_upvotes(comment.score)
        economic_signals = cls._calculate_economic_signals(comment, annotated_data)
        time_decay = cls._calculate_time_decay(comment.created_date)
        verification_boost = cls._get_verification_boost(comment.created_by, annotated_data)
        
        
        base_score = log_upvotes + economic_signals
        academic_score = base_score * time_decay * verification_boost
        
        academic_score = CommentQualityFilter.apply_quality_penalty(academic_score, comment)
        
        return {
            'score': academic_score,
            'components': {
                'log_upvotes': log_upvotes,
                'economic_signals': economic_signals,
                'time_decay': time_decay,
                'verification_boost': verification_boost,
                'base_score': base_score,
                'is_low_quality': CommentQualityFilter.is_low_quality(comment)
            }
        }
    
    @classmethod
    def _calculate_log_upvotes(cls, score: int) -> float:
        if score <= 0:
            return 0.0
        
        return cls.config.LOG_BASE_MULTIPLIER * math.log10(score + 1)
    
    @classmethod
    def _calculate_economic_signals(cls, comment, annotated_data=None) -> float:
        if annotated_data and 'tip_amount' in annotated_data:
            tips = annotated_data['tip_amount'] or Decimal('0')
            bounty_awards = annotated_data.get('bounty_award_amount', Decimal('0')) or Decimal('0')
        elif hasattr(comment, 'tip_amount') and hasattr(comment, 'bounty_award_amount'):
            tips = comment.tip_amount or Decimal('0')
            bounty_awards = comment.bounty_award_amount or Decimal('0')
        else:
            tips = comment.purchases.filter(
                purchase_type=Purchase.BOOST,
                paid_status=Purchase.PAID
            ).aggregate(
                total=Sum(Cast('amount', DecimalField(max_digits=19, decimal_places=10)))
            )['total'] or Decimal('0')
            
            bounty_awards = comment.bounty_solution.filter(
                status=BountySolution.Status.AWARDED
            ).aggregate(
                total=Sum('awarded_amount')
            )['total'] or Decimal('0')
        
        total_economic = float(tips) + float(bounty_awards)
        
        if total_economic > 0:
            return math.log10(total_economic + 1) * 10
        
        return 0.0
    
    @classmethod
    def _calculate_time_decay(cls, created_date: Optional[datetime]) -> float:
        if not created_date:
            return 1.0
        
        now = timezone.now()
        age = now - created_date
        days_old = age.total_seconds() / cls.config.SECONDS_PER_DAY
        
        decay_factor = math.pow(cls.config.DECAY_BASE, days_old / cls.config.HALF_LIFE_DAYS)
        
        return decay_factor
    
    @classmethod
    def _get_verification_boost(cls, user, annotated_data=None) -> float:
        if not user:
            return 1.0
        
        if annotated_data and 'is_verified_user' in annotated_data:
            if annotated_data['is_verified_user']:
                return cls.config.VERIFICATION_MULTIPLIER
        else:
            try:
                if user.is_verified:
                    return cls.config.VERIFICATION_MULTIPLIER
            except Exception:
                pass
        
        return 1.0