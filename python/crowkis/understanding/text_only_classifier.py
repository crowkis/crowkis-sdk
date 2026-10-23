"""TextOnlyClassifier: a classifier written for ``classify(text)``, in the slot that also passes the call's facts."""

from __future__ import annotations

import inspect
from typing import Any, Sequence

from .slots import Classifier, Reading

# The arguments the slot passes: the turn and the call's facts.
SLOT_ARGUMENTS = 2


class TextOnlyClassifier:
    """Adapter: a classifier that reads the turn alone (the P2-P4 protocol, ``classify(text)``) keeps
    working now that the slot also passes the call's facts; it simply does not get them."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @classmethod
    def fit(cls, classifier: Any) -> Classifier:
        """``classifier`` itself when it takes the facts, else this adapter around it."""
        try:
            inspect.signature(classifier.classify).bind(*(None,) * SLOT_ARGUMENTS)
        except TypeError:
            return cls(classifier)
        except ValueError:  # no signature to read (a builtin): pass the facts and let it say
            return classifier
        return classifier

    def classify(self, text: str, facts: Sequence[str] = ()) -> Reading:
        return self._inner.classify(text)
