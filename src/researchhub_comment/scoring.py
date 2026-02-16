from datetime import datetime, timezone
from typing import Dict, Any, Optional
import math


class CommentScorer:
    @classmethod
    def calculate_score(cls, comment, annotated_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        annotated_data = annotated_data or {}
        
        engagement_score = cls._calculate_engagement_signals(comment)
        economic_score = cls._calculate_economic_signals(comment, annotated_data)
        time_decay = cls._calculate_time_decay(comment)
        verification_boost = cls._calculate_verification_boost(comment, annotated_data)
        
        raw_score = (engagement_score + economic_score) * time_decay
        final_score = raw_score * verification_boost
        
        return {
            'score': final_score,
            'raw_score': raw_score,
            'engagement_score': engagement_score,
            'economic_score': economic_score,
            'time_decay': time_decay,
            'verification_boost': verification_boost,
            'breakdown': {
                'vote_score': engagement_score,
                'tip_score': economic_score,
                'time_factor': time_decay,
                'verification_factor': verification_boost
            }
        }
    
    @classmethod
    def _calculate_engagement_signals(cls, comment) -> float:
        vote_count = max(0, getattr(comment, 'score', 0))
        if vote_count > 0:
            return math.log10(vote_count + 1) * 10
        return 0.0
    
    @classmethod
    def _calculate_economic_signals(cls, comment, annotated_data=None) -> float:
        if not annotated_data:
            return 0.0
            
        tip_amount = annotated_data.get('tip_amount', 0)
        bounty_amount = annotated_data.get('bounty_award_amount', 0)
        
        # Handle None values
        tips = float(tip_amount) if tip_amount is not None else 0.0
        bounty_awards = float(bounty_amount) if bounty_amount is not None else 0.0
        
        total_economic = tips + bounty_awards
        if total_economic > 0:
            return math.log10(total_economic + 1) * 10
        return 0.0
    
    @classmethod
    def _calculate_time_decay(cls, comment) -> float:
        created_date = comment.created_date
        if created_date.tzinfo is None:
            created_date = created_date.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        days_old = (now - created_date).days
        
        half_life_days = 30
        decay_factor = 0.5 ** (days_old / half_life_days)
        
        return decay_factor
    
    @classmethod
    def _calculate_verification_boost(cls, comment, annotated_data=None) -> float:
        if not annotated_data:
            return 1.0
            
        is_verified = annotated_data.get('is_verified_user', False)
        # Handle None value explicitly
        if is_verified is None:
            is_verified = False
            
        return 3.0 if is_verified else 1.0