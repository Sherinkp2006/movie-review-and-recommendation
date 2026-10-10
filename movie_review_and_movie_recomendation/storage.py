import csv
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from django.conf import settings

from .models import MovieReview

CSV_FIELDS = ('id', 'title', 'director', 'language', 'release_date', 'rating', 'review', 'genre')
_thread_lock = threading.RLock()


def _csv_path():
    return Path(getattr(settings, 'MOVIE_CSV_PATH', settings.BASE_DIR / 'movie_database.csv'))


@contextmanager
def _file_lock(csv_path):
    lock_path = csv_path.with_suffix(csv_path.suffix + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+b') as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b'\0')
            lock_file.flush()
        lock_file.seek(0)
        if os.name == 'nt':
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _parse_date(value, row_number):
    if not value:
        return None
    for date_format in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    raise ValueError(f'Invalid release_date on CSV row {row_number}: {value!r}')


def _read_reviews(csv_path):
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []
    with csv_path.open('r', newline='', encoding='utf-8-sig') as csv_file:
        reader = csv.DictReader(csv_file)
        missing_fields = (set(CSV_FIELDS) - {'genre'}) - set(reader.fieldnames or ())
        if missing_fields:
            raise ValueError(
                f'{csv_path} is missing required CSV columns: {", ".join(sorted(missing_fields))}'
            )
        reviews = []
        for row_number, row in enumerate(reader, start=2):
            try:
                reviews.append(
                    MovieReview(
                        id=int(row['id']),
                        title=row['title'],
                        director=row['director'] or None,
                        language=row['language'] or None,
                        release_date=_parse_date(row['release_date'], row_number),
                        rating=float(row['rating']),
                        review=row['review'],
                        genre=row.get('genre', '') or '',
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f'Invalid movie review on CSV row {row_number}: {exc}') from exc
    return reviews


def _write_reviews(csv_path, reviews):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            newline='',
            encoding='utf-8',
            dir=csv_path.parent,
            prefix=f'.{csv_path.name}.',
            suffix='.tmp',
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for review in sorted(reviews, key=lambda item: item.id, reverse=True):
                writer.writerow({
                    'id': review.id,
                    'title': review.title,
                    'director': review.director or '',
                    'language': review.language or '',
                    'release_date': review.release_date.strftime('%d/%m/%Y')
                    if review.release_date
                    else '',
                    'rating': review.rating,
                    'review': review.review,
                    'genre': review.genre,
                })
        os.replace(temporary_path, csv_path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def all_reviews():
    csv_path = _csv_path()
    with _thread_lock, _file_lock(csv_path):
        return sorted(_read_reviews(csv_path), key=lambda review: review.id, reverse=True)


def create_review(
    *,
    title,
    director=None,
    language=None,
    release_date=None,
    review,
    rating,
    genre=None,
):
    if isinstance(release_date, str) and release_date:
        release_date = _parse_date(release_date, 'new record')
    csv_path = _csv_path()
    with _thread_lock, _file_lock(csv_path):
        reviews = _read_reviews(csv_path)
        new_id = max((item.id for item in reviews), default=0) + 1
        movie_review = MovieReview(
            id=new_id,
            title=title,
            director=director or None,
            language=language or None,
            release_date=release_date,
            review=review,
            rating=float(rating),
            genre=genre or next(
                (item.genre for item in reviews if item.title == title and item.genre),
                '',
            ),
        )
        reviews.append(movie_review)
        _write_reviews(csv_path, reviews)
    return movie_review


def update_movie_metadata(
    title,
    *,
    new_title,
    director=None,
    language=None,
    release_date=None,
    genre=None,
):
    if isinstance(release_date, str) and release_date:
        release_date = _parse_date(release_date, 'movie update')
    csv_path = _csv_path()
    with _thread_lock, _file_lock(csv_path):
        reviews = _read_reviews(csv_path)
        matching_reviews = [item for item in reviews if item.title == title]
        if not matching_reviews:
            return 0
        for review in matching_reviews:
            review.title = new_title
            review.director = director or None
            review.language = language or None
            review.release_date = release_date
            review.genre = genre or ''
        _write_reviews(csv_path, reviews)
    return len(matching_reviews)


def update_review(review_id, *, review_text, rating):
    csv_path = _csv_path()
    with _thread_lock, _file_lock(csv_path):
        reviews = _read_reviews(csv_path)
        updated_review = next((item for item in reviews if item.id == review_id), None)
        if updated_review is None:
            return None
        updated_review.review = review_text
        updated_review.rating = float(rating)
        _write_reviews(csv_path, reviews)
        return updated_review


def delete_review(review_id):
    csv_path = _csv_path()
    with _thread_lock, _file_lock(csv_path):
        reviews = _read_reviews(csv_path)
        remaining_reviews = [item for item in reviews if item.id != review_id]
        if len(remaining_reviews) == len(reviews):
            return False
        _write_reviews(csv_path, remaining_reviews)
    return True


def delete_movie(title):
    csv_path = _csv_path()
    with _thread_lock, _file_lock(csv_path):
        reviews = _read_reviews(csv_path)
        remaining_reviews = [item for item in reviews if item.title != title]
        deleted_count = len(reviews) - len(remaining_reviews)
        if deleted_count:
            _write_reviews(csv_path, remaining_reviews)
    return deleted_count


def create_reviews(reviews):
    """Append a batch of MovieReview instances, assigning IDs from the CSV store."""
    csv_path = _csv_path()
    with _thread_lock, _file_lock(csv_path):
        stored_reviews = _read_reviews(csv_path)
        next_id = max((item.id for item in stored_reviews), default=0) + 1
        for review in reviews:
            review.id = next_id
            next_id += 1
            stored_reviews.append(review)
        _write_reviews(csv_path, stored_reviews)


def set_movie_genres(genres_by_title):
    """Persist a title-to-genre mapping on every review record for each movie."""
    csv_path = _csv_path()
    with _thread_lock, _file_lock(csv_path):
        reviews = _read_reviews(csv_path)
        for review in reviews:
            if review.title in genres_by_title:
                review.genre = genres_by_title[review.title]
        _write_reviews(csv_path, reviews)
