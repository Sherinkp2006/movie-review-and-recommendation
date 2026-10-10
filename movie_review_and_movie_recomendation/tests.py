import csv
import tempfile
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import MovieReviewForm
from .genres import primary_genre
from .management.commands.sync_movie_genres import _matching_candidates
from .sentiment import (
    classify_review_sentiment,
    classify_review_sentiments,
    preprocess_review,
)
from .storage import (
    all_reviews,
    create_review,
    delete_movie,
    delete_review,
    set_movie_genres,
    update_movie_metadata,
    update_review,
)
from .views import ADMIN_PORTAL_SESSION_KEY


class CSVBackedTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.temp_dir = tempfile.TemporaryDirectory()
        training_data_path = Path(self.temp_dir.name) / 'sentiment_training.csv'
        with training_data_path.open('w', newline='', encoding='utf-8') as training_file:
            writer = csv.DictWriter(training_file, fieldnames=('review', 'sentiment'))
            writer.writeheader()
            training_examples = [
                {
                    'review': 'I loved this brilliant excellent wonderful film and recommend it',
                    'sentiment': 'positive',
                },
                {
                    'review': 'Beautiful delightful uplifting movie with fantastic acting',
                    'sentiment': 'positive',
                },
                {
                    'review': 'Great acting and a moving enjoyable story',
                    'sentiment': 'positive',
                },
                {
                    'review': 'Amazing movie and wonderful performances',
                    'sentiment': 'positive',
                },
                {
                    'review': 'I hated this terrible awful boring film',
                    'sentiment': 'negative',
                },
                {
                    'review': 'Dull disappointing depressing movie and bad ending',
                    'sentiment': 'negative',
                },
                {
                    'review': 'Poor acting and a weak unpleasant story',
                    'sentiment': 'negative',
                },
                {
                    'review': 'Terrible miserable movie; hated every minute',
                    'sentiment': 'negative',
                },
            ]
            writer.writerows(training_examples * 10)
        self.settings_override = override_settings(
            MOVIE_CSV_PATH=Path(self.temp_dir.name) / 'movie_database.csv',
            SENTIMENT_TRAINING_DATA_PATH=training_data_path,
        )
        self.settings_override.enable()
        self.addCleanup(self.cleanup_csv_storage)

    def cleanup_csv_storage(self):
        self.settings_override.disable()
        self.temp_dir.cleanup()

    def add_review(self, **kwargs):
        if isinstance(kwargs.get('release_date'), str):
            kwargs['release_date'] = date.fromisoformat(kwargs['release_date'])
        return create_review(**kwargs)


class MovieReviewCSVStorageTests(CSVBackedTestCase):
    def test_movie_review_persists_in_csv_with_dd_mm_yyyy_date(self):
        review = self.add_review(
            title='Example Film',
            director=None,
            language=None,
            release_date='2020-01-02',
            review='A long and thoughtful movie review.',
            rating=8.5,
        )

        self.assertEqual(review.id, 1)
        self.assertEqual(all_reviews()[0].release_date, date(2020, 1, 2))
        csv_path = Path(self.temp_dir.name) / 'movie_database.csv'
        with csv_path.open(newline='', encoding='utf-8') as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(rows[0]['release_date'], '02/01/2020')

    def test_new_review_gets_next_id_and_is_listed_first(self):
        self.add_review(title='Old Film', review='Old', rating=5)
        newest = self.add_review(title='New Film', review='Newest', rating=8)

        self.assertEqual(newest.id, 2)
        self.assertEqual([item.title for item in all_reviews()], ['New Film', 'Old Film'])

    def test_review_and_movie_admin_storage_operations(self):
        first = self.add_review(
            title='Example Film',
            director='First Director',
            language='English',
            release_date='2020-01-01',
            review='First review.',
            rating=8,
            genre='drama',
        )
        second = self.add_review(
            title='Example Film',
            director='First Director',
            language='English',
            release_date='2020-01-01',
            review='Second review.',
            rating=6,
        )

        self.assertEqual(
            update_movie_metadata(
                'Example Film',
                new_title='Updated Film',
                director='New Director',
                language='French',
                release_date='2021-02-03',
                genre='comedy',
            ),
            2,
        )
        self.assertEqual(update_review(first.id, review_text='Edited review.', rating=9).review, 'Edited review.')
        self.assertTrue(delete_review(second.id))
        self.assertEqual(delete_movie('Updated Film'), 1)
        self.assertEqual(all_reviews(), [])

    def test_synced_genre_is_persisted_on_each_review_for_a_movie(self):
        self.add_review(title='Example Film', review='Review one', rating=8)
        self.add_review(title='Example Film', review='Review two', rating=7)

        set_movie_genres({'Example Film': 'drama film; comedy film'})

        self.assertEqual(
            [review.genre for review in all_reviews()],
            ['drama film; comedy film', 'drama film; comedy film'],
        )

    def test_genre_lookup_prefers_release_year_match_over_undated_candidate(self):
        candidates = {
            'Q2010': {'years': {2010}, 'genres': {'science fiction film'}},
            'Qunknown': {'years': set(), 'genres': {'drama film'}},
        }

        matches = _matching_candidates(candidates, {2010})

        self.assertEqual(matches, [candidates['Q2010']])

    def test_wikidata_genre_lists_reduce_to_one_concise_label(self):
        self.assertEqual(
            primary_genre(
                'adventure film; drama film; hard science fiction; '
                'science fiction film; thriller film; time-travel film'
            ),
            'Science Fiction Film',
        )
        self.assertEqual(
            primary_genre('crime film; crime thriller film; drama film; thriller film'),
            'Crime Thriller',
        )
        self.assertEqual(
            primary_genre('comedy drama; drama film; romance film; romantic comedy film'),
            'Romantic Comedy',
        )
        self.assertEqual(
            primary_genre('buddy film; musical film; sport film'),
            '',
        )
        self.assertEqual(
            primary_genre('association football film'),
            '',
        )


class MoviePageTests(CSVBackedTestCase):
    def setUp(self):
        super().setUp()
        self.first_review = self.add_review(
            title='Drishyam',
            director='Jeethu Joseph',
            language='Malayalam',
            release_date='2013-01-01',
            review='An excellent, wonderful, thrilling film!',
            rating=9.0,
        )
        self.add_review(
            title='Drishyam',
            director='Jeethu Joseph',
            language='Malayalam',
            release_date='2013-01-01',
            review='I loved this brilliant and moving movie.',
            rating=8.0,
        )
        self.add_review(
            title='Drishyam 2',
            director='Jeethu Joseph',
            language='Malayalam',
            release_date='2021-01-01',
            review='An engaging sequel.',
            rating=9.5,
        )

    def test_movie_catalog_lists_each_title_once_and_links_to_its_reviews(self):
        response = self.client.get(reverse('movie_review_and_movie_recomendation:movie-list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['movies']), 2)
        movie_genres = {movie['title']: movie['genre'] for movie in response.context['movies']}
        movie_labels = {movie['title']: movie['genre_label'] for movie in response.context['movies']}
        movie_rating_percentages = {
            movie['title']: movie['rating_percentage']
            for movie in response.context['movies']
        }
        self.assertEqual(movie_genres['Drishyam'], '')
        self.assertEqual(movie_genres['Drishyam 2'], '')
        self.assertEqual(movie_labels['Drishyam'], '')
        self.assertEqual(movie_labels['Drishyam 2'], '')
        self.assertEqual(movie_rating_percentages['Drishyam'], 85.0)
        self.assertEqual(movie_rating_percentages['Drishyam 2'], 95.0)
        self.assertContains(
            response,
            'aria-label="Overall rating: 8.5 out of 10; negative at the left, positive at the right"',
        )
        self.assertContains(response, 'style="left: 85.0%;"')
        self.assertContains(response, 'Negative')
        self.assertContains(response, 'Positive')
        self.assertContains(response, '2013')
        self.assertContains(response, 'Genre not found')
        self.assertNotContains(response, '01/01/2013')
        self.assertContains(
            response,
            reverse(
                'movie_review_and_movie_recomendation:movie-reviews',
                args=[self.first_review.pk],
            ),
        )

    def test_movie_catalog_filters_and_sorts_by_average_rating(self):
        url = reverse('movie_review_and_movie_recomendation:movie-list')
        filtered = self.client.get(
            url,
            {'language': 'Malayalam', 'director': 'Jeethu Joseph', 'release_year': '2021'},
        )
        self.assertEqual([movie['title'] for movie in filtered.context['movies']], ['Drishyam 2'])
        self.assertEqual(filtered.context['selected_release_year'], '2021')

        highest_first = self.client.get(url, {'rating_order': 'highest'})
        self.assertEqual(
            [movie['title'] for movie in highest_first.context['movies']],
            ['Drishyam 2', 'Drishyam'],
        )
        lowest_first = self.client.get(url, {'rating_order': 'lowest'})
        self.assertEqual(
            [movie['title'] for movie in lowest_first.context['movies']],
            ['Drishyam', 'Drishyam 2'],
        )

    def test_review_page_filters_and_lists_most_recent_first(self):
        response = self.client.get(
            reverse('movie_review_and_movie_recomendation:review-list'),
            {'language': 'Malayalam', 'director': 'Jeethu Joseph', 'release_year': '2021'},
        )
        self.assertContains(response, 'Released 2021')
        self.assertNotContains(response, '01/01/2021')
        self.assertEqual(
            [review.title for review in response.context['reviews']],
            ['Drishyam 2'],
        )

        newest = self.add_review(
            title='Karnan',
            director='Mari Selvaraj',
            language='Tamil',
            release_date='2021-01-01',
            review='A powerful social drama.',
            rating=8.7,
        )
        first = self.add_review(
            title='Mersal',
            director='Atlee',
            language='Tamil',
            release_date='2017-01-01',
            review='An entertaining commercial action film.',
            rating=7.9,
        )
        ordered = self.client.get(reverse('movie_review_and_movie_recomendation:review-list'))
        self.assertEqual(
            [review.pk for review in ordered.context['reviews'][:2]],
            [first.pk, newest.pk],
        )

    def test_review_export_contains_all_current_csv_records(self):
        response = self.client.get(
            reverse('movie_review_and_movie_recomendation:review-export-csv')
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        rows = list(csv.DictReader(response.content.decode('utf-8').splitlines()))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['title'], 'Drishyam 2')
        self.assertEqual(rows[0]['release_date'], '01/01/2021')

    def test_movie_title_page_shows_reviews_for_that_title(self):
        self.add_review(
            title='Drishyam',
            director='Jeethu Joseph',
            language='Malayalam',
            release_date='2013-01-01',
            review='A weak entry. It was terrible, awful, and boring; I hated it.',
            rating=2,
        )
        self.add_review(
            title='Drishyam',
            director='Jeethu Joseph',
            language='Malayalam',
            release_date='2013-01-01',
            review='I absolutely loved this brilliant, excellent film!',
            rating=9,
        )
        self.add_review(
            title='Drishyam',
            director='Jeethu Joseph',
            language='Malayalam',
            release_date='2013-01-01',
            review='The film was released in 2013.',
            rating=5,
        )
        response = self.client.get(
            reverse(
                'movie_review_and_movie_recomendation:movie-reviews',
                args=[self.first_review.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['reviews']), 5)
        self.assertEqual(response.context['positive_review_count'], 3)
        self.assertEqual(response.context['negative_review_count'], 1)
        self.assertContains(response, 'Positive reviews')
        self.assertContains(response, 'Negative reviews')
        self.assertContains(response, 'An excellent, wonderful, thrilling film!')
        self.assertContains(response, 'I loved this brilliant and moving movie.')
        self.assertContains(response, 'A weak entry. It was terrible, awful, and boring; I hated it.')
        self.assertNotContains(response, 'An engaging sequel.')

    def test_review_sentiment_classifier_identifies_positive_negative_and_neutral_text(self):
        self.assertEqual(
            classify_review_sentiment('I absolutely loved this brilliant, excellent film!'),
            'positive',
        )
        self.assertEqual(
            classify_review_sentiment('It was terrible, awful, and boring; I hated it.'),
            'negative',
        )
        self.assertEqual(
            classify_review_sentiment('The film was released in 2013.'),
            'neutral',
        )

    def test_sentiment_preprocessing_cleans_html_and_preserves_negation(self):
        self.assertEqual(
            preprocess_review("I didn't enjoy these movies. <br />"),
            'not enjoy movie',
        )
        self.assertEqual(
            preprocess_review('Although it had potential, it was less satisfying.'),
            'although potential less satisfy',
        )

    def test_sentiment_classifier_predicts_multiple_reviews_with_one_model(self):
        self.assertEqual(
            classify_review_sentiments([
                'A wonderful, brilliant and deeply enjoyable film.',
                'A terrible, dull and painfully boring movie.',
            ]),
            ['positive', 'negative'],
        )

    def test_low_rating_reviews_help_train_domain_specific_negative_sentiment(self):
        review_text = (
            'Baahubali: The Beginning had potential, but the emotional impact '
            'made the viewing experience less satisfying.'
        )
        for index, negative_review in enumerate([
            'The movie had potential, but the ending was less satisfying.',
            'It was a disappointing film and difficult to enjoy.',
            'Although the story sounded promising, the acting was terrible and boring.',
            'This film was not enjoyable; it was a waste of time.',
            'The movie looked good at first but turned into a dull disappointment.',
        ]):
            self.add_review(
                title=f'Negative Example {index}',
                review=negative_review,
                rating=2,
            )
        for index, positive_review in enumerate([
            'An enjoyable movie with a satisfying story and wonderful acting.',
            'Although it started slowly, this became an excellent and moving film.',
            'I loved the performances and thought the ending was brilliant.',
            'A delightful, entertaining movie that I would recommend.',
            'The story was engaging and the film was thoroughly enjoyable.',
        ]):
            self.add_review(
                title=f'Positive Example {index}',
                review=positive_review,
                rating=9,
            )

        self.assertEqual(classify_review_sentiment(review_text), 'negative')

    def test_movie_reviews_returns_404_for_unknown_id(self):
        response = self.client.get(
            reverse('movie_review_and_movie_recomendation:movie-reviews', args=[99999])
        )
        self.assertEqual(response.status_code, 404)

    def test_recommendations_filter_by_saved_genre_and_show_movie_details(self):
        self.add_review(
            title='Action Match',
            director='Sample Director',
            language='Tamil',
            release_date='2020-01-01',
            review='A unique first review with no category clues.',
            rating=7.0,
            genre='action; adventure film',
        )
        latest_review = self.add_review(
            title='Action Match',
            director='Sample Director',
            language='Tamil',
            release_date='2020-01-01',
            review='Unique hidden review: explosive action chase sequences.',
            rating=9.0,
            genre='action; adventure film',
        )

        response = self.client.post(
            reverse('movie_review_and_movie_recomendation:recommendation'),
            {'movie_type': 'Action Film', 'language': '', 'director': ''},
        )

        self.assertEqual(response.status_code, 200)
        recommendations = response.context['recommendations']
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]['title'], 'Action Match')
        self.assertEqual(recommendations[0]['genre'], 'action; adventure film')
        self.assertEqual(recommendations[0]['genre_label'], 'Action Film')
        self.assertEqual(recommendations[0]['first_review_id'], latest_review.id)
        self.assertEqual(recommendations[0]['average_rating'], 8.0)
        self.assertEqual(recommendations[0]['review_count'], 2)
        self.assertContains(response, 'Action Match')
        self.assertContains(response, 'Sample Director')
        self.assertContains(response, 'Tamil')
        self.assertContains(response, '2020')
        self.assertContains(response, 'Action Film')
        self.assertNotContains(response, 'Unique hidden review')

    def test_recommendations_can_filter_movies_by_predicted_sentiment(self):
        positive_review = self.add_review(
            title='Positive Match',
            review='A wonderful brilliant movie that I loved.',
            rating=8.5,
        )
        negative_review = self.add_review(
            title='Negative Match',
            review='A terrible boring movie that I hated.',
            rating=4.0,
        )

        response = self.client.post(
            reverse('movie_review_and_movie_recomendation:recommendation'),
            {
                'movie_type': '',
                'language': '',
                'director': '',
                'sentiment': 'positive',
            },
        )

        recommendations = response.context['recommendations']
        recommended_titles = [movie['title'] for movie in recommendations]
        self.assertIn(positive_review.title, recommended_titles)
        self.assertNotIn(negative_review.title, recommended_titles)
        positive_match = next(
            movie for movie in recommendations if movie['title'] == positive_review.title
        )
        self.assertEqual(positive_match['sentiment_label'], 'positive')

class MovieReviewFormTests(CSVBackedTestCase):
    def test_form_choices_are_read_from_csv(self):
        self.add_review(
            title='Drishyam',
            director='Jeethu Joseph',
            language='Malayalam',
            review='A gripping mystery.',
            rating=9.0,
        )

        form = MovieReviewForm()
        self.assertIn(('Drishyam', 'Drishyam'), form.fields['title'].choices)
        self.assertIn(('Jeethu Joseph', 'Jeethu Joseph'), form.fields['new_director'].choices)
        self.assertIn(('Malayalam', 'Malayalam'), form.fields['new_language'].choices)

    def test_form_saves_new_movie_and_accepts_dd_mm_yyyy(self):
        form = MovieReviewForm(data={
            'title': '__new__',
            'new_title': 'New Language Film',
            'new_director': '__new__',
            'custom_director': ' A Director ',
            'new_language': '__new__',
            'custom_language': ' Example Language ',
            'new_release_date': '02/01/2024',
            'review': 'An enjoyable film.',
            'rating': '8',
        })

        self.assertTrue(form.is_valid(), form.errors)
        movie_review = form.save()

        self.assertEqual(movie_review.director, 'A Director')
        self.assertEqual(movie_review.language, 'Example Language')
        self.assertEqual(movie_review.release_date, date(2024, 1, 2))
        self.assertEqual(all_reviews()[0].title, 'New Language Film')


class AdminPortalTests(CSVBackedTestCase):
    def setUp(self):
        super().setUp()
        self.staff_user = get_user_model().objects.create_user(
            username='movie-admin',
            password='secure-test-password',
            is_staff=True,
        )
        self.regular_user = get_user_model().objects.create_user(
            username='movie-user',
            password='secure-test-password',
        )

    def login_staff_for_test(self):
        self.client.force_login(self.staff_user)
        session = self.client.session
        session[ADMIN_PORTAL_SESSION_KEY] = True
        session.save()

    def test_home_links_to_admin_login_and_portal_requires_staff_login(self):
        home = self.client.get(reverse('movie_review_and_movie_recomendation:home'))
        self.assertContains(
            home,
            reverse('movie_review_and_movie_recomendation:admin-login'),
        )

        portal_url = reverse('movie_review_and_movie_recomendation:admin-portal')
        response = self.client.get(portal_url)
        self.assertRedirects(
            response,
            f'{reverse("movie_review_and_movie_recomendation:admin-login")}?next={portal_url}',
        )

        self.client.force_login(self.staff_user)
        response = self.client.get(portal_url)
        self.assertRedirects(
            response,
            f'{reverse("movie_review_and_movie_recomendation:admin-login")}?next={portal_url}',
        )

        session = self.client.session
        session[ADMIN_PORTAL_SESSION_KEY] = True
        session.save()
        self.assertEqual(self.client.get(portal_url).status_code, 200)
        self.client.get(reverse('movie_review_and_movie_recomendation:home'))
        self.assertRedirects(
            self.client.get(portal_url),
            f'{reverse("movie_review_and_movie_recomendation:admin-login")}?next={portal_url}',
        )

        self.client.force_login(self.regular_user)
        session = self.client.session
        session[ADMIN_PORTAL_SESSION_KEY] = True
        session.save()
        self.assertEqual(self.client.get(portal_url).status_code, 403)

    def test_admin_login_and_portal_access(self):
        response = self.client.post(
            reverse('movie_review_and_movie_recomendation:admin-login'),
            {
                'username': 'movie-admin',
                'password': 'secure-test-password',
                'next': reverse('movie_review_and_movie_recomendation:admin-portal'),
            },
        )
        self.assertRedirects(
            response,
            reverse('movie_review_and_movie_recomendation:admin-portal'),
        )
        self.assertEqual(
            self.client.get(
                reverse('movie_review_and_movie_recomendation:admin-portal')
            ).status_code,
            200,
        )
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        response = self.client.post(
            reverse('movie_review_and_movie_recomendation:admin-logout')
        )
        self.assertRedirects(
            response,
            reverse('movie_review_and_movie_recomendation:home'),
        )

    def test_staff_can_create_edit_and_delete_movie_and_reviews(self):
        self.login_staff_for_test()
        portal_url = reverse('movie_review_and_movie_recomendation:admin-portal')

        response = self.client.post(
            reverse('movie_review_and_movie_recomendation:admin-movie-add'),
            {
                'title': 'Admin Film',
                'director': 'A Director',
                'language': 'English',
                'release_date': '2020-01-02',
                'genre': 'drama film',
                'review': 'A thoughtful first review.',
                'rating': '8.5',
            },
        )
        self.assertRedirects(response, portal_url)
        movie_review = all_reviews()[0]
        self.assertEqual(movie_review.title, 'Admin Film')
        portal = self.client.get(portal_url)
        self.assertContains(portal, 'Admin Film')
        self.assertContains(portal, 'Add review')

        response = self.client.post(
            reverse(
                'movie_review_and_movie_recomendation:admin-movie-edit',
                args=[movie_review.id],
            ),
            {
                'title': 'Updated Admin Film',
                'director': 'A New Director',
                'language': 'French',
                'release_date': '2021-03-04',
                'genre': 'comedy film',
            },
        )
        self.assertRedirects(response, portal_url)
        movie_review = all_reviews()[0]
        self.assertEqual(movie_review.title, 'Updated Admin Film')
        self.assertEqual(movie_review.director, 'A New Director')

        response = self.client.post(
            reverse(
                'movie_review_and_movie_recomendation:admin-review-add',
                args=[movie_review.id],
            ),
            {'review': 'Another audience review.', 'rating': '7'},
        )
        self.assertRedirects(response, portal_url)
        reviews = all_reviews()
        self.assertEqual(len(reviews), 2)

        response = self.client.post(
            reverse(
                'movie_review_and_movie_recomendation:admin-review-edit',
                args=[reviews[0].id],
            ),
            {'review': 'Edited audience review.', 'rating': '6.5'},
        )
        self.assertRedirects(response, portal_url)
        self.assertEqual(all_reviews()[0].review, 'Edited audience review.')

        response = self.client.post(
            reverse(
                'movie_review_and_movie_recomendation:admin-review-delete',
                args=[reviews[1].id],
            )
        )
        self.assertRedirects(response, portal_url)
        self.assertEqual(len(all_reviews()), 1)

        response = self.client.post(
            reverse(
                'movie_review_and_movie_recomendation:admin-movie-delete',
                args=[all_reviews()[0].id],
            )
        )
        self.assertRedirects(response, portal_url)
        self.assertEqual(all_reviews(), [])

    def test_destructive_admin_actions_require_post(self):
        self.login_staff_for_test()
        movie = self.add_review(title='Protected Film', review='Review.', rating=5)
        response = self.client.get(
            reverse(
                'movie_review_and_movie_recomendation:admin-movie-delete',
                args=[movie.id],
            )
        )
        self.assertEqual(response.status_code, 405)
        self.assertEqual(len(all_reviews()), 1)

    def test_authenticated_staff_must_still_submit_login_form_for_each_visit(self):
        self.client.force_login(self.staff_user)
        login_url = reverse('movie_review_and_movie_recomendation:admin-login')
        response = self.client.get(login_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin Login')
        self.assertNotIn(ADMIN_PORTAL_SESSION_KEY, self.client.session)
