from unittest import TestCase

from research_ai.prompts.expert_finder_prompts import build_profile_match_user_prompt
from research_ai.services.expert_finder.profile_match import parse_profile_match_response


class ProfileMatchPromptTests(TestCase):
    def test_build_profile_match_user_prompt_lists_candidates(self):
        prompt = build_profile_match_user_prompt(
            expert_name="Robert M. Cox",
            academic_title="Assistant Professor",
            affiliation="Georgia State University",
            expertise="virology",
            email="rcox@gsu.edu",
            notes="",
            profile_kind="x",
            candidates=[
                {
                    "url": "https://x.com/wrong",
                    "title": "Robert Cox",
                    "description": "Sports",
                },
                {
                    "url": "https://x.com/right",
                    "title": "Robert Cox GSU",
                    "description": "Assistant Professor",
                },
            ],
        )
        self.assertIn("Robert M. Cox", prompt)
        self.assertIn("Georgia State University", prompt)
        self.assertIn("1. title:", prompt)
        self.assertIn("https://x.com/right", prompt)
        self.assertIn('{"selected_index":', prompt)

    def test_parse_accepts_fenced_json(self):
        candidates = [{"url": "https://x.com/a", "title": "", "description": ""}]
        raw = 'Here you go:\n```json\n{"selected_index": 1}\n```'
        self.assertEqual(parse_profile_match_response(raw, candidates), "https://x.com/a")
