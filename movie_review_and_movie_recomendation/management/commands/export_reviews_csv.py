import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from movie_review_and_movie_recomendation.storage import all_reviews


class Command(BaseCommand):
    help = 'Export all movie review records to a CSV file.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            default='movie_reviews_export.csv',
            help='File path for the generated CSV export.',
        )

    def handle(self, *args, **options):
        project_root = Path(__file__).resolve().parents[3]
        output_path = Path(options['output'])
        if not output_path.is_absolute():
            output_path = project_root / output_path

        with output_path.open('w', newline='', encoding='utf-8') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([
                'id', 'title', 'director', 'language', 'release_date', 'rating', 'review', 'genre'
            ])

            reviews = all_reviews()
            for review in reviews:
                writer.writerow([
                    review.id,
                    review.title,
                    review.director or '',
                    review.language or '',
                    review.release_date.strftime('%d/%m/%Y') if review.release_date else '',
                    review.rating,
                    review.review,
                    review.genre,
                ])

        self.stdout.write(
            self.style.SUCCESS(f'Exported {len(reviews)} reviews to {output_path}')
        )
