"""
title: Agent Evaluator
description: Validate and score specialist outputs against fixed quality rubrics.
version: 2.0.0
"""

import json


RUBRICS = {
    "CODER": ({"correctness": 3, "requirements_met": 2, "code_quality": 2, "error_handling": 2, "edge_cases": 1}, 7),
    "SEARCHER": ({"source_quality": 3, "completeness": 3, "accuracy": 2, "relevance": 2}, 6),
    "BUILDER": ({"structure": 3, "deps_resolved": 2, "docs": 2, "reproducible": 3}, 7),
    "REVIEWER": ({"issues_found": 4, "clarity": 3, "actionability": 3}, 7),
    "DESIGNER": ({"clarity": 3, "usability": 3, "completeness": 4}, 6),
    "CONSULTANT": ({"depth": 3, "actionable": 3, "evidence": 2, "risk": 2}, 7),
}


class Tools:
    def evaluate_output(self, agent: str, scores_json: str) -> str:
        """Score an output. agent is CODER, SEARCHER, BUILDER, REVIEWER, DESIGNER, or CONSULTANT."""
        role = agent.upper().strip()
        if role not in RUBRICS:
            return json.dumps({"status": "error", "error": "Unknown agent", "valid_agents": sorted(RUBRICS)})
        try:
            supplied = json.loads(scores_json)
            if not isinstance(supplied, dict):
                raise ValueError("scores_json must be an object")
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})
        criteria, threshold = RUBRICS[role]
        scores = {}
        for name, maximum in criteria.items():
            raw = supplied.get(name, 0)
            if not isinstance(raw, (int, float)):
                return json.dumps({"status": "error", "error": f"Score for {name} must be numeric"})
            scores[name] = max(0, min(raw, maximum))
        earned = sum(scores.values())
        total = sum(criteria.values())
        passed = earned >= threshold
        return json.dumps({"agent": role, "scores": scores, "score": f"{earned:g}/{total}", "threshold": threshold, "passed": passed, "verdict": "PASS" if passed else "FAIL"})
