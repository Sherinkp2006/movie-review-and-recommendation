from pathlib import Path

from django.core.management.base import BaseCommand

from movie_review_and_movie_recomendation.models import MovieReview
from movie_review_and_movie_recomendation.storage import create_reviews


class Command(BaseCommand):
    help = 'Import IMDb sentiment review text files into the database.'

    def handle(self, *args, **options):
        base_dir = Path('/home/sherinkp/Downloads/aclImdb_v1/aclImdb')
        if not base_dir.exists():
            raise FileNotFoundError(f'IMDb dataset not found at {base_dir}')

        import_batch = []
        imported = 0

        for split in ('train', 'test'):
            for label in ('pos', 'neg'):
                folder = base_dir / split / label
                if not folder.exists():
                    self.stderr.write(f'Skipping missing folder: {folder}')
                    continue

                for review_file in sorted(folder.glob('*.txt')):
                    review_text = review_file.read_text(encoding='utf-8', errors='replace').strip()
                    if not review_text:
                        continue

                    rating_value = int(review_file.stem.split('_')[-1])
                    title = f'{split}_{label}_{review_file.stem}'

                    import_batch.append(
                        MovieReview(
                            id=0,
                            title=title,
                            director=None,
                            language=None,
                            release_date=None,
                            review=review_text,
                            rating=float(rating_value),
                        )
                    )

        if import_batch:
            create_reviews(import_batch)
            imported = len(import_batch)

        self.stdout.write(
            self.style.SUCCESS(f'Imported {imported} IMDb review records into the database.')
        )
