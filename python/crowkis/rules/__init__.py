"""The SDK's check stages as rules: question (stage 1), hit (stage 2) and save (stage 3).

Each rule is a small class with a ``name`` and a ``check``; a RuleChain runs a stage's rules in
order and the first objection wins; a RuleSet holds every chain a session runs."""

from .chain import FloorRuleLocked, RuleChain, UnknownRule
from .rule import HitRule, QuestionRule, Rule, SaveRule
from .rule_set import RuleSet

__all__ = ["FloorRuleLocked", "HitRule", "QuestionRule", "Rule", "RuleChain", "RuleSet", "SaveRule", "UnknownRule"]
