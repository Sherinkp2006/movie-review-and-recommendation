from dataclasses import dataclass
from datetime import date


@dataclass
class MovieReview:
    id: int
    title: str
    director: str | None
    language: str | None
    release_date: date | None
    review: str
    rating: float
    genre: str = ''

    @property
    def pk(self):
        return self.id
