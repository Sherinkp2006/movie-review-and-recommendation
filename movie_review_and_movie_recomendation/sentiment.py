import csv
import html
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from django.conf import settings
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

ReviewSentiment = Literal['positive', 'negative', 'neutral']

_STOP_WORDS = ENGLISH_STOP_WORDS.difference({
    'although',
    'barely',
    'despite',
    'hardly',
    'however',
    'less',
    'never',
    'no',
    'nor',
    'not',
    'though',
    'without',
})
_POLARITY_CONFIDENCE_THRESHOLD = 0.7
_RATING_REVIEW_SAMPLE_WEIGHT = 10.0
_IRREGULAR_LEMMAS = {
    'am': 'be',
    'are': 'be',
    'best': 'good',
    'better': 'good',
    'did': 'do',
    'does': 'do',
    'done': 'do',
    'excellent': 'excellent',
    'had': 'have',
    'has': 'have',
    'is': 'be',
    'movies': 'movie',
    'was': 'be',
    'were': 'be',
    'worst': 'bad',
    'worse': 'bad',
}
_RESTORE_E = {
    'breathtaking',
    'caring',
    'dancing',
    'exciting',
    'hating',
    'hoping',
    'improving',
    'liking',
    'loving',
    'making',
    'moving',
    'riding',
    'smiling',
    'taking',
    'using',
    'writing',
}
_TOKEN_PATTERN = re.compile(r"[a-z]+(?:'[a-z]+)?")
_HTML_TAG_PATTERN = re.compile(r'<[^>]+>')


def _lemmatize(token: str) -> str:
    if token in _IRREGULAR_LEMMAS:
        return _IRREGULAR_LEMMAS[token]
    if token.endswith('ies') and len(token) > 4:
        return f'{token[:-3]}y'
    if token.endswith('ing') and len(token) > 5:
        lemma = token[:-3]
        if len(lemma) > 2 and lemma[-1] == lemma[-2]:
            lemma = lemma[:-1]
        if token in _RESTORE_E:
            lemma += 'e'
        return lemma
    if token.endswith('ed') and len(token) > 4:
        lemma = token[:-2]
        if len(lemma) > 2 and lemma[-1] == lemma[-2]:
            lemma = lemma[:-1]
        if f'{lemma}e' in {'love', 'hate', 'move', 'like', 'use', 'create', 'excite'}:
            lemma += 'e'
        return lemma
    if token.endswith(('ches', 'shes', 'xes', 'zes')) and len(token) > 4:
        return token[:-2]
    if token.endswith('s') and not token.endswith(('ss', 'us', 'is')) and len(token) > 3:
        return token[:-1]
    return token


def preprocess_review(review_text: str) -> str:
    cleaned_text = html.unescape(_HTML_TAG_PATTERN.sub(' ', review_text)).lower()
    cleaned_text = re.sub(r"n't\b", ' not', cleaned_text)
    tokens = _TOKEN_PATTERN.findall(cleaned_text)
    normalized_tokens = (_lemmatize(token) for token in tokens if len(token) > 1)
    return ' '.join(token for token in normalized_tokens if token not in _STOP_WORDS)


def _read_training_data(dataset_path: Path) -> tuple[list[str], list[str]]:
    if not dataset_path.is_file():
        raise FileNotFoundError(
            f'Sentiment training dataset not found: {dataset_path}. '
            'Set SENTIMENT_TRAINING_DATA_PATH to a CSV with review and sentiment columns.'
        )

    review_texts = []
    labels = []
    with dataset_path.open('r', newline='', encoding='utf-8-sig') as dataset_file:
        reader = csv.DictReader(dataset_file)
        columns = {column.casefold(): column for column in (reader.fieldnames or [])}
        if 'review' not in columns or 'sentiment' not in columns:
            raise ValueError(
                f'{dataset_path} must contain "review" and "sentiment" columns.'
            )
        for row_number, row in enumerate(reader, start=2):
            review_text = (row.get(columns['review']) or '').strip()
            sentiment = (row.get(columns['sentiment']) or '').strip().casefold()
            if not review_text:
                continue
            if sentiment in {'positive', 'pos'}:
                label = 'positive'
            elif sentiment in {'negative', 'neg'}:
                label = 'negative'
            else:
                raise ValueError(
                    f'Unsupported sentiment label on CSV row {row_number}: {sentiment!r}'
                )
            review_texts.append(review_text)
            labels.append(label)

    if set(labels) != {'positive', 'negative'}:
        raise ValueError(
            f'{dataset_path} must contain at least one positive and one negative review.'
        )
    return review_texts, labels


def _read_rating_training_data(dataset_path: Path) -> tuple[list[str], list[str]]:
    if not dataset_path.is_file():
        return [], []

    review_ratings: dict[str, tuple[float, int]] = {}
    with dataset_path.open('r', newline='', encoding='utf-8-sig') as dataset_file:
        reader = csv.DictReader(dataset_file)
        columns = {column.casefold(): column for column in (reader.fieldnames or [])}
        if 'review' not in columns or 'rating' not in columns:
            raise ValueError(
                f'{dataset_path} must contain "review" and "rating" columns.'
            )
        for row_number, row in enumerate(reader, start=2):
            review_text = (row.get(columns['review']) or '').strip()
            if not review_text:
                continue
            try:
                rating = float(row.get(columns['rating']) or '')
            except ValueError as exc:
                raise ValueError(
                    f'Invalid rating on CSV row {row_number} in {dataset_path}.'
                ) from exc
            previous_total, previous_count = review_ratings.get(review_text, (0, 0))
            review_ratings[review_text] = (previous_total + rating, previous_count + 1)

    review_texts = []
    labels = []
    for review_text, (rating_total, rating_count) in review_ratings.items():
        average_rating = rating_total / rating_count
        if average_rating <= 4:
            label = 'negative'
        elif average_rating >= 8:
            label = 'positive'
        elif 5 <= average_rating <= 6:
            label = 'neutral'
        else:
            continue
        review_texts.append(review_text)
        labels.append(label)

    return review_texts, labels


@lru_cache(maxsize=2)
def _train_pipeline(
    dataset_path: str,
    modified_ns: int,
    file_size: int,
    rating_data_path: str,
    rating_data_modified_ns: int,
    rating_data_file_size: int,
) -> Pipeline:
    del modified_ns, file_size, rating_data_modified_ns, rating_data_file_size
    review_texts, labels = _read_training_data(Path(dataset_path))
    rating_review_texts, rating_labels = _read_rating_training_data(
        Path(rating_data_path)
    )
    sample_weights = (
        [1.0] * len(review_texts)
        + [_RATING_REVIEW_SAMPLE_WEIGHT] * len(rating_review_texts)
    )
    review_texts.extend(rating_review_texts)
    labels.extend(rating_labels)
    pipeline = Pipeline([
        (
            'tfidf',
            TfidfVectorizer(
                preprocessor=preprocess_review,
                tokenizer=str.split,
                token_pattern=None,
                lowercase=False,
                ngram_range=(1, 2),
                max_features=100_000,
                min_df=1,
            ),
        ),
        ('classifier', LogisticRegression(C=2, max_iter=300, random_state=42)),
    ])
    pipeline.fit(review_texts, labels, classifier__sample_weight=sample_weights)
    return pipeline


def _sentiment_model() -> Pipeline:
    dataset_path = Path(getattr(
        settings,
        'SENTIMENT_TRAINING_DATA_PATH',
        settings.BASE_DIR / 'new files' / 'IMDB Dataset.csv',
    ))
    if not dataset_path.is_file():
        raise FileNotFoundError(
            f'Sentiment training dataset not found: {dataset_path}. '
            'Set SENTIMENT_TRAINING_DATA_PATH to a CSV with review and sentiment columns.'
        )
    metadata = dataset_path.stat()
    rating_data_path = Path(settings.MOVIE_CSV_PATH)
    if rating_data_path.is_file():
        rating_data_metadata = rating_data_path.stat()
        rating_data_modified_ns = rating_data_metadata.st_mtime_ns
        rating_data_file_size = rating_data_metadata.st_size
    else:
        rating_data_modified_ns = 0
        rating_data_file_size = 0
    return _train_pipeline(
        str(dataset_path.resolve()),
        metadata.st_mtime_ns,
        metadata.st_size,
        str(rating_data_path.resolve()),
        rating_data_modified_ns,
        rating_data_file_size,
    )


def classify_review_sentiments(review_texts: list[str]) -> list[ReviewSentiment]:
    if not review_texts:
        return []

    model = _sentiment_model()
    probabilities = model.predict_proba(review_texts)
    classes = list(model.classes_)
    positive_index = classes.index('positive')
    negative_index = classes.index('negative')
    neutral_index = classes.index('neutral') if 'neutral' in classes else None
    sentiments: list[ReviewSentiment] = []
    for row in probabilities:
        positive_probability = row[positive_index]
        if (
            neutral_index is not None
            and row[neutral_index] >= max(
                row[positive_index],
                row[negative_index],
            )
        ):
            sentiments.append('neutral')
            continue
        is_neutral = (
            1 - _POLARITY_CONFIDENCE_THRESHOLD
            <= positive_probability
            <= _POLARITY_CONFIDENCE_THRESHOLD
        )
        if is_neutral:
            sentiments.append('neutral')
        elif positive_probability > _POLARITY_CONFIDENCE_THRESHOLD:
            sentiments.append('positive')
        else:
            sentiments.append('negative')
    return sentiments


def classify_review_sentiment(review_text: str) -> ReviewSentiment:
    return classify_review_sentiments([review_text])[0]
