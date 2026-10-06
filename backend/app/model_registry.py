"""Single source of truth for every text classifier we compare and for the one the app ships.

The experiments (experiments/run_experiments.py) tune these on the VALIDATION split, pick the winner by
validation macro-F1, and write the choice to data/model_config.json. The app reads that file at start-up.
"""
from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.decomposition import TruncatedSVD
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, VotingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, RidgeClassifier, SGDClassifier
from sklearn.naive_bayes import ComplementNB, MultinomialNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline, make_union
from sklearn.svm import LinearSVC


def vectorizer(kind: str = "char_word", char_range=(2, 5), word_range=(1, 2), min_df: int = 1):
    ch = lambda: TfidfVectorizer(analyzer="char_wb", ngram_range=tuple(char_range), lowercase=True,
                                 sublinear_tf=True, min_df=min_df)
    wd = lambda: TfidfVectorizer(analyzer="word", ngram_range=tuple(word_range), lowercase=True,
                                 sublinear_tf=True, min_df=min_df)
    if kind == "char":
        return ch()
    if kind == "word":
        return wd()
    return make_union(ch(), wd())


class SoftmaxRidge(BaseEstimator, ClassifierMixin):
    """RidgeClassifier with softmax-scaled decision scores so it can report (pseudo-)probabilities."""

    def __init__(self, alpha: float = 1.0, temperature: float = 0.25):
        self.alpha, self.temperature = alpha, temperature

    def fit(self, X, y):
        self.m_ = RidgeClassifier(alpha=self.alpha).fit(X, y)
        self.classes_ = self.m_.classes_
        return self

    def predict_proba(self, X):
        z = self.m_.decision_function(X) / self.temperature
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def predict(self, X):
        return self.m_.predict(X)


def _cal(est, cv: int = 3):
    return CalibratedClassifierCV(est, cv=cv, method="sigmoid")


# name -> (builder(params) -> estimator pipeline, default params, small tuning grid)
def _lr(p):
    return make_pipeline(vectorizer(p.get("feat", "char_word")), LogisticRegression(C=p.get("C", 30.0), max_iter=3000))


def _svm(p):
    return make_pipeline(vectorizer(p.get("feat", "char_word")), _cal(LinearSVC(C=p.get("C", 1.0))))


def _nb(p):
    return make_pipeline(vectorizer(p.get("feat", "char_word")), MultinomialNB(alpha=p.get("alpha", 0.05)))


def _cnb(p):
    return make_pipeline(vectorizer(p.get("feat", "char_word")), ComplementNB(alpha=p.get("alpha", 0.1)))


def _sgd(p):
    return make_pipeline(vectorizer(p.get("feat", "char_word")),
                         SGDClassifier(loss="modified_huber", alpha=p.get("alpha", 1e-4), max_iter=200, random_state=0))


def _ridge(p):
    return make_pipeline(vectorizer(p.get("feat", "char_word")), SoftmaxRidge(alpha=p.get("alpha", 1.0)))


def _knn(p):
    return make_pipeline(vectorizer(p.get("feat", "char_word")),
                         KNeighborsClassifier(n_neighbors=p.get("k", 5), metric="cosine", weights="distance"))


def _rf(p):
    return make_pipeline(vectorizer(p.get("feat", "char_word"), min_df=2),
                         RandomForestClassifier(n_estimators=p.get("n", 300), random_state=0, n_jobs=-1,
                                                max_features="sqrt", class_weight="balanced_subsample"))


def _hgb(p):
    return make_pipeline(vectorizer(p.get("feat", "char_word"), min_df=2), TruncatedSVD(p.get("svd", 150), random_state=0),
                         HistGradientBoostingClassifier(max_iter=p.get("iters", 150), learning_rate=p.get("lr", 0.1),
                                                        random_state=0))


def _mlp_head(p):
    return make_pipeline(TruncatedSVD(p.get("svd", 256), random_state=0),
                         MLPClassifier(hidden_layer_sizes=(p.get("h", 256),), alpha=p.get("alpha", 1e-4),
                                       max_iter=200, early_stopping=False, random_state=0))


def _mlp(p):  # TF-IDF -> 256-d latent semantic space (SVD) -> one hidden layer
    return make_pipeline(vectorizer(p.get("feat", "char_word"), min_df=2), _mlp_head(p))


def _vote(p):
    return make_pipeline(vectorizer(p.get("feat", "char_word")), VotingClassifier(
        [("lr", LogisticRegression(C=p.get("C", 30.0), max_iter=3000)),
         ("svm", _cal(LinearSVC(C=p.get("svmC", 1.0)))),
         ("mlp", _mlp_head(p))],
        voting="soft"))


def _maj(p):
    return make_pipeline(vectorizer("word"), DummyClassifier(strategy="prior"))


REGISTRY = {
    "majority": (_maj, {}, [{}]),
    "naive_bayes": (_nb, {"alpha": 0.05}, [{"alpha": a} for a in (0.01, 0.05, 0.2)]),
    "complement_nb": (_cnb, {"alpha": 0.1}, [{"alpha": a} for a in (0.03, 0.1, 0.5)]),
    "logreg": (_lr, {"C": 30.0}, [{"C": c} for c in (3.0, 10.0, 30.0, 100.0)]),
    "linear_svm": (_svm, {"C": 1.0}, [{"C": c} for c in (0.3, 1.0, 3.0)]),
    "sgd_huber": (_sgd, {"alpha": 1e-4}, [{"alpha": a} for a in (1e-5, 1e-4, 1e-3)]),
    "ridge": (_ridge, {"alpha": 1.0}, [{"alpha": a} for a in (0.3, 1.0, 3.0)]),
    "knn": (_knn, {"k": 5}, [{"k": k} for k in (1, 3, 7)]),
    "random_forest": (_rf, {"n": 300}, [{"n": 200}, {"n": 400}]),
    "hist_gb": (_hgb, {"svd": 150}, [{"svd": 100, "iters": 100}, {"svd": 200, "iters": 150}]),
    "mlp": (_mlp, {"h": 256}, [{"h": 128}, {"h": 256, "alpha": 1e-3}]),
    "soft_vote": (_vote, {}, [{"C": 30.0}, {"C": 100.0}]),
}


def build(name: str, params: dict | None = None):
    builder, default, _ = REGISTRY[name]
    return builder({**default, **(params or {})})
