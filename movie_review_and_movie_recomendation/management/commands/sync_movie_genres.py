import json
import time
from collections import defaultdict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError

from movie_review_and_movie_recomendation.storage import all_reviews, set_movie_genres

WIKIDATA_ENDPOINT = 'https://query.wikidata.org/sparql'
BATCH_SIZE = 15


def _sparql_literal(value):
    return f'{json.dumps(value, ensure_ascii=True)}@en'


def _query_wikidata(titles):
    title_values = ' '.join(_sparql_literal(title) for title in titles)
    query = f'''
        SELECT ?requestedTitle ?film ?genreLabel ?publicationDate WHERE {{
          VALUES ?requestedTitle {{ {title_values} }}
          ?film rdfs:label ?requestedTitle;
                wdt:P31/wdt:P279* wd:Q11424;
                wdt:P136 ?genre.
          OPTIONAL {{ ?film wdt:P577 ?publicationDate. }}
          SERVICE wikibase:label {{
            bd:serviceParam wikibase:language "en".
          }}
        }}
    '''
    request = Request(
        f'{WIKIDATA_ENDPOINT}?{urlencode({"query": query, "format": "json"})}',
        headers={
            'Accept': 'application/sparql-results+json',
            'User-Agent': 'CinematicExpressoGenreSync/1.0 (movie genre import)',
        },
    )
    try:
        with urlopen(request, timeout=45) as response:
            data = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CommandError(f'Wikidata genre lookup failed: {exc}') from exc

    candidates = defaultdict(lambda: defaultdict(lambda: {'genres': set(), 'years': set()}))
    for binding in data['results']['bindings']:
        title = binding['requestedTitle']['value']
        entity = binding['film']['value'].rsplit('/', 1)[-1]
        candidate = candidates[title][entity]
        candidate['genres'].add(binding['genreLabel']['value'])
        publication_date = binding.get('publicationDate', {}).get('value', '')
        if publication_date[:4].isdigit():
            candidate['years'].add(int(publication_date[:4]))
    return candidates


def _matching_candidates(title_candidates, expected_years):
    if not expected_years:
        return list(title_candidates.values())
    year_matches = [
        candidate
        for candidate in title_candidates.values()
        if candidate['years'] & expected_years
    ]
    if year_matches:
        return year_matches
    if len(title_candidates) == 1:
        only_candidate = next(iter(title_candidates.values()))
        if not only_candidate['years']:
            return [only_candidate]
    return []


class Command(BaseCommand):
    help = 'Look up movie genres by exact title in Wikidata and save them to the movie CSV.'

    def handle(self, *args, **options):
        reviews = all_reviews()
        years_by_title = defaultdict(set)
        for review in reviews:
            if review.release_date:
                years_by_title[review.title].add(review.release_date.year)
        titles = sorted({review.title for review in reviews})
        genres_by_title = {}
        missing_titles = []
        ambiguous_titles = []

        for offset in range(0, len(titles), BATCH_SIZE):
            batch = titles[offset:offset + BATCH_SIZE]
            candidates = _query_wikidata(batch)
            for title in batch:
                title_candidates = candidates.get(title, {})
                expected_years = years_by_title[title]
                matching_candidates = _matching_candidates(title_candidates, expected_years)
                if len(matching_candidates) == 1:
                    genres_by_title[title] = '; '.join(
                        sorted(matching_candidates[0]['genres'], key=str.casefold)
                    )
                elif len(matching_candidates) > 1:
                    ambiguous_titles.append(title)
                else:
                    missing_titles.append(title)
            if offset + BATCH_SIZE < len(titles):
                time.sleep(1)

        set_movie_genres({
            title: genres_by_title.get(title, '')
            for title in titles
        })
        self.stdout.write(
            self.style.SUCCESS(
                f'Saved Wikidata genres for {len(genres_by_title)} of {len(titles)} movies.'
            )
        )
        if missing_titles:
            self.stdout.write(f'No exact title/year genre match: {", ".join(missing_titles)}')
        if ambiguous_titles:
            self.stdout.write(
                f'Ambiguous title/year matches left unchanged: {", ".join(ambiguous_titles)}'
            )
