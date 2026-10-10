def split_genres(value):
    """Return the individual Wikidata genres stored in a CSV record."""
    return tuple(genre.strip() for genre in (value or '').split(';') if genre.strip())


GENRE_LABELS = (
    (('romantic comedy',), 'Romantic Comedy'),
    (('psychological thriller',), 'Psychological Thriller'),
    (('crime thriller',), 'Crime Thriller'),
    (('action thriller',), 'Action Thriller'),
    (('science fiction action',), 'Science Fiction Action'),
    (('comedy horror',), 'Comedy Horror'),
    (('historical drama',), 'Historical Drama'),
    (('crime drama',), 'Crime Drama'),
    (('science fiction', 'hard science fiction', 'dystopian fiction', 'cyberpunk'), 'Science Fiction Film'),
    (('superhero',), 'Action Film'),
    (('fantasy', 'high fantasy', 'magic realist'), 'Fantasy Film'),
    (('horror', 'ghost film'), 'Horror Film'),
    (('mystery', 'detective film'), 'Mystery Thriller'),
    (('crime', 'gangster', 'heist'), 'Crime Drama'),
    (('action', 'martial arts'), 'Action Film'),
    (('adventure',), 'Adventure Film'),
    (('comedy', 'black comedy', 'tragicomedy'), 'Comedy Film'),
    (('romance',), 'Romance Film'),
    (('war',), 'War Film'),
    (('thriller', 'suspense'), 'Thriller Film'),
    (('western',), 'Western Film'),
    (('drama',), 'Drama Film'),
)


def primary_genre(value):
    """Reduce Wikidata's multiple genre tags to one consistent, concise label."""
    genres = tuple(genre.casefold() for genre in split_genres(value))
    for keywords, label in GENRE_LABELS:
        if any(keyword in genre for keyword in keywords for genre in genres):
            return label
    return ''
