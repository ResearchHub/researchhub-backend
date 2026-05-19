DEFAULT_SCORE = 100
TRUSTED_THRESHOLD = 50
RESTRICTED_THRESHOLD = 150

GRADE_SCALE = [
    (0, "A+"),
    (13, "A"),
    (27, "A-"),
    (41, "B+"),
    (55, "B"),
    (69, "B-"),
    (83, "C+"),
    (97, "C"),
    (111, "C-"),
    (125, "D+"),
    (139, "D"),
    (149, "D-"),
]


def score_to_grade(score):
    for threshold, grade in GRADE_SCALE:
        if score <= threshold:
            return grade
    return "F"
