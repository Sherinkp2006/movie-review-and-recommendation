import csv
import random
from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, redirect_to_login
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import (
    AdminMovieForm,
    AdminMovieMetadataForm,
    AdminReviewForm,
    MovieReviewForm,
    RecommendationForm,
)
from .genres import primary_genre
from .sentiment import classify_review_sentiments
from .storage import (
    all_reviews,
    create_review,
    delete_movie as delete_stored_movie,
    delete_review as delete_stored_review,
    update_movie_metadata,
    update_review as update_stored_review,
)

ADMIN_PORTAL_SESSION_KEY = 'movie_review_and_movie_recomendation_admin_portal'


class AdminPortalLoginView(LoginView):
    template_name = 'movie_review_and_movie_recomendation/admin_login.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session[ADMIN_PORTAL_SESSION_KEY] = True
        self.request.session.set_expiry(0)
        return response


def home(request):
    return render(request, 'movie_review_and_movie_recomendation/home.html')


def staff_required(view_func):
    @wraps(view_func)
    @login_required(login_url='movie_review_and_movie_recomendation:admin-login')
    def wrapped_view(request, *args, **kwargs):
        if not request.session.get(ADMIN_PORTAL_SESSION_KEY):
            return redirect_to_login(
                request.get_full_path(),
                login_url=reverse('movie_review_and_movie_recomendation:admin-login'),
            )
        if not request.user.is_active or not request.user.is_staff:
            return HttpResponseForbidden('Staff access is required.')
        return view_func(request, *args, **kwargs)

    return wrapped_view


@staff_required
@require_POST
def admin_logout(request):
    auth_logout(request)
    return redirect('movie_review_and_movie_recomendation:home')


@staff_required
def admin_portal(request):
    query = request.GET.get('q', '').strip().casefold()
    reviews = all_reviews()
    review_count = len(reviews)
    movies_by_title = {}
    for review in reviews:
        movie = movies_by_title.setdefault(review.title, {
            'title': review.title,
            'director': review.director,
            'language': review.language,
            'release_date': review.release_date,
            'genre': review.genre,
            'first_review_id': review.id,
            'rating_total': 0,
            'review_count': 0,
        })
        movie['first_review_id'] = min(movie['first_review_id'], review.id)
        movie['rating_total'] += review.rating
        movie['review_count'] += 1
        if not movie['genre'] and review.genre:
            movie['genre'] = review.genre
    movies = [
        {
            **movie,
            'average_rating': movie['rating_total'] / movie['review_count'],
            'genre_label': primary_genre(movie['genre']),
        }
        for movie in movies_by_title.values()
    ]
    if query:
        movies = [
            movie for movie in movies
            if query in movie['title'].casefold()
            or query in (movie['director'] or '').casefold()
        ]
        reviews = [
            review for review in reviews
            if any(
                query in (value or '').casefold()
                for value in (review.title, review.director, review.review)
            )
        ]
    page = Paginator(reviews, 25).get_page(request.GET.get('page'))
    return render(
        request,
        'movie_review_and_movie_recomendation/admin_portal.html',
        {
            'movies': movies,
            'reviews': page,
            'query': request.GET.get('q', '').strip(),
            'movie_count': len(movies_by_title),
            'review_count': review_count,
        },
    )


@staff_required
def admin_add_movie(request):
    form = AdminMovieForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        title = form.cleaned_data['title']
        if any(review.title.casefold() == title.casefold() for review in all_reviews()):
            form.add_error('title', 'A movie with this title already exists.')
        else:
            create_review(
                title=title,
                director=form.cleaned_data['director'],
                language=form.cleaned_data['language'],
                release_date=form.cleaned_data['release_date'],
                genre=form.cleaned_data['genre'],
                review=form.cleaned_data['review'],
                rating=form.cleaned_data['rating'],
            )
            messages.success(request, f'{title} was added to the movie catalog.')
            return redirect('movie_review_and_movie_recomendation:admin-portal')
    return render(
        request,
        'movie_review_and_movie_recomendation/admin_movie_form.html',
        {'form': form, 'heading': 'Add movie', 'submit_label': 'Add movie'},
    )


@staff_required
def admin_edit_movie(request, movie_id):
    reviews = all_reviews()
    selected_review = next((item for item in reviews if item.id == movie_id), None)
    if selected_review is None:
        raise Http404('Movie not found.')
    movie_reviews = [item for item in reviews if item.title == selected_review.title]
    latest_review = max(movie_reviews, key=lambda item: item.id)
    initial = {
        'title': selected_review.title,
        'director': latest_review.director or '',
        'language': latest_review.language or '',
        'release_date': latest_review.release_date,
        'genre': latest_review.genre,
    }
    form = AdminMovieMetadataForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        new_title = form.cleaned_data['title']
        if new_title.casefold() != selected_review.title.casefold() and any(
            review.title.casefold() == new_title.casefold()
            for review in reviews
        ):
            form.add_error('title', 'Another movie already uses this title.')
        else:
            updated_count = update_movie_metadata(
                selected_review.title,
                new_title=new_title,
                director=form.cleaned_data['director'],
                language=form.cleaned_data['language'],
                release_date=form.cleaned_data['release_date'],
                genre=form.cleaned_data['genre'],
            )
            if not updated_count:
                raise Http404('Movie not found.')
            messages.success(request, f'{new_title} details were updated.')
            return redirect('movie_review_and_movie_recomendation:admin-portal')
    return render(
        request,
        'movie_review_and_movie_recomendation/admin_movie_form.html',
        {
            'form': form,
            'heading': f'Edit {selected_review.title}',
            'submit_label': 'Save movie details',
        },
    )


@staff_required
@require_POST
def admin_delete_movie(request, movie_id):
    selected_review = next(
        (item for item in all_reviews() if item.id == movie_id),
        None,
    )
    if selected_review is None:
        raise Http404('Movie not found.')
    title = selected_review.title
    deleted_count = delete_stored_movie(title)
    if not deleted_count:
        raise Http404('Movie not found.')
    messages.success(
        request,
        f'{title} and its {deleted_count} review(s) were deleted.',
    )
    return redirect('movie_review_and_movie_recomendation:admin-portal')


@staff_required
def admin_add_review(request, movie_id):
    movie = next(
        (item for item in all_reviews() if item.id == movie_id),
        None,
    )
    if movie is None:
        raise Http404('Movie not found.')
    form = AdminReviewForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        create_review(
            title=movie.title,
            director=movie.director,
            language=movie.language,
            release_date=movie.release_date,
            genre=movie.genre,
            review=form.cleaned_data['review'],
            rating=form.cleaned_data['rating'],
        )
        messages.success(request, f'A review was added for {movie.title}.')
        return redirect('movie_review_and_movie_recomendation:admin-portal')
    return render(
        request,
        'movie_review_and_movie_recomendation/admin_review_form.html',
        {'form': form, 'heading': f'Add review for {movie.title}'},
    )


@staff_required
def admin_edit_review(request, review_id):
    review = next(
        (item for item in all_reviews() if item.id == review_id),
        None,
    )
    if review is None:
        raise Http404('Review not found.')
    form = AdminReviewForm(
        request.POST or None,
        initial={'review': review.review, 'rating': review.rating},
    )
    if request.method == 'POST' and form.is_valid():
        updated_review = update_stored_review(
            review_id,
            review_text=form.cleaned_data['review'],
            rating=form.cleaned_data['rating'],
        )
        if updated_review is None:
            raise Http404('Review not found.')
        messages.success(request, f'The review for {review.title} was updated.')
        return redirect('movie_review_and_movie_recomendation:admin-portal')
    return render(
        request,
        'movie_review_and_movie_recomendation/admin_review_form.html',
        {'form': form, 'heading': f'Edit review for {review.title}'},
    )


@staff_required
@require_POST
def admin_delete_review(request, review_id):
    if not delete_stored_review(review_id):
        raise Http404('Review not found.')
    messages.success(request, 'The review was deleted.')
    return redirect('movie_review_and_movie_recomendation:admin-portal')


def _filter_reviews(reviews, search_query='', selected_language='', selected_director='', selected_release_year='', include_language_search=False):
    if search_query:
        query = search_query.casefold()
        searchable_fields = ['title', 'director', 'review']
        if include_language_search:
            searchable_fields.append('language')
        reviews = [
            item for item in reviews
            if any(query in (getattr(item, field) or '').casefold() for field in searchable_fields)
        ]
    if selected_language:
        reviews = [item for item in reviews if item.language == selected_language]
    if selected_director:
        reviews = [item for item in reviews if item.director == selected_director]
    if selected_release_year:
        reviews = [
            item for item in reviews
            if item.release_date and str(item.release_date.year) == selected_release_year
        ]
    return reviews


def _filter_options(reviews):
    languages = sorted({item.language for item in reviews if item.language})
    directors = sorted({item.director for item in reviews if item.director})
    release_years = sorted(
        {item.release_date.replace(month=1, day=1) for item in reviews if item.release_date},
        reverse=True,
    )
    return languages, directors, release_years


def movie_list(request):
    search_query = request.GET.get('q', '').strip()
    selected_language = request.GET.get('language', '').strip()
    selected_director = request.GET.get('director', '').strip()
    selected_release_year = request.GET.get('release_year', '').strip()
    selected_rating_order = request.GET.get('rating_order', '').strip()
    all_movie_reviews = all_reviews()
    reviews = _filter_reviews(
        all_movie_reviews,
        search_query=search_query,
        selected_language=selected_language,
        selected_director=selected_director,
        selected_release_year=selected_release_year,
        include_language_search=True,
    )

    grouped_movies = {}
    for review in reviews:
        group_key = (review.title, review.director, review.language, review.release_date)
        movie = grouped_movies.setdefault(group_key, {
            'title': review.title,
            'director': review.director,
            'language': review.language,
            'release_date': review.release_date,
            'genre': review.genre,
            'first_review_id': review.id,
            'rating_total': 0,
            'review_count': 0,
        })
        movie['first_review_id'] = min(movie['first_review_id'], review.id)
        movie['rating_total'] += review.rating
        movie['review_count'] += 1
        if not movie['genre'] and review.genre:
            movie['genre'] = review.genre
    movies = [
        {
            **movie,
            'average_rating': movie['rating_total'] / movie['review_count'],
        }
        for movie in grouped_movies.values()
    ]
    for movie in movies:
        del movie['rating_total']
        movie['genre_label'] = primary_genre(movie['genre'])
        movie['rating_percentage'] = max(
            0,
            min(100, movie['average_rating'] * 10),
        )

    if selected_rating_order == 'highest':
        movies.sort(key=lambda movie: (-movie['average_rating'], movie['title']))
    elif selected_rating_order == 'lowest':
        movies.sort(key=lambda movie: (movie['average_rating'], movie['title']))
    else:
        selected_rating_order = ''
        movies.sort(key=lambda movie: movie['title'])

    languages, directors, release_years = _filter_options(all_movie_reviews)
    return render(
        request,
        'movie_review_and_movie_recomendation/list_movie.html',
        {
            'movies': movies,
            'search_query': search_query,
            'languages': languages,
            'directors': directors,
            'release_years': release_years,
            'selected_language': selected_language,
            'selected_director': selected_director,
            'selected_release_year': selected_release_year,
            'selected_rating_order': selected_rating_order,
        },
    )


def movie_reviews(request, movie_id):
    all_movie_reviews = all_reviews()
    movie = next((item for item in all_movie_reviews if item.id == movie_id), None)
    if movie is None:
        raise Http404('Movie review not found.')
    reviews = [item for item in all_movie_reviews if item.title == movie.title]
    sentiments = classify_review_sentiments([review.review for review in reviews])
    for review, sentiment in zip(reviews, sentiments):
        review.sentiment = sentiment
    positive_review_count = sentiments.count('positive')
    negative_review_count = sentiments.count('negative')
    random.shuffle(reviews)
    return render(
        request,
        'movie_review_and_movie_recomendation/movie_reviews.html',
        {
            'movie': movie,
            'reviews': reviews,
            'positive_review_count': positive_review_count,
            'negative_review_count': negative_review_count,
        },
    )


def get_filtered_reviews(search_query='', selected_language='', selected_director='', selected_release_year=''):
    return _filter_reviews(
        all_reviews(),
        search_query=search_query,
        selected_language=selected_language,
        selected_director=selected_director,
        selected_release_year=selected_release_year,
    )


def review_list(request):
    search_query = request.GET.get('q', '').strip()
    selected_language = request.GET.get('language', '').strip()
    selected_director = request.GET.get('director', '').strip()
    selected_release_year = request.GET.get('release_year', '').strip()
    all_movie_reviews = all_reviews()
    reviews = _filter_reviews(
        all_movie_reviews,
        search_query=search_query,
        selected_language=selected_language,
        selected_director=selected_director,
        selected_release_year=selected_release_year,
    )
    sentiments = classify_review_sentiments([review.review for review in reviews])
    for review, sentiment in zip(reviews, sentiments):
        review.sentiment = sentiment
    languages, directors, release_years = _filter_options(all_movie_reviews)
    return render(
        request,
        'movie_review_and_movie_recomendation/list_reviews.html',
        {
            'reviews': reviews,
            'search_query': search_query,
            'languages': languages,
            'directors': directors,
            'release_years': release_years,
            'selected_language': selected_language,
            'selected_director': selected_director,
            'selected_release_year': selected_release_year,
        },
    )


def export_reviews_csv(request):
    reviews = get_filtered_reviews(
        search_query=request.GET.get('q', '').strip(),
        selected_language=request.GET.get('language', '').strip(),
        selected_director=request.GET.get('director', '').strip(),
        selected_release_year=request.GET.get('release_year', '').strip(),
    )
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="movie_reviews.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'id', 'title', 'director', 'language', 'release_date', 'rating', 'review', 'genre'
    ])
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
    return response


def add_review(request):
    if request.method == 'POST':
        form = MovieReviewForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Movie review added successfully.')
            return redirect('movie_review_and_movie_recomendation:review-list')
    else:
        form = MovieReviewForm()
    return render(request, 'movie_review_and_movie_recomendation/add_review.html', {'form': form})


def recommendation(request):
    form = RecommendationForm(request.POST or None)
    recommendations = []
    if request.method == 'POST' and form.is_valid():
        filters = form.cleaned_data
        movie_reviews = all_reviews()
        sentiments = classify_review_sentiments([review.review for review in movie_reviews])
        grouped_movies = {}
        for review, sentiment in zip(movie_reviews, sentiments):
            movie = grouped_movies.setdefault(review.title, {
                'title': review.title,
                'director': review.director,
                'language': review.language,
                'release_date': review.release_date,
                'genre': review.genre,
                'first_review_id': review.id,
                'rating_total': 0,
                'review_count': 0,
                'positive_review_count': 0,
                'negative_review_count': 0,
                'neutral_review_count': 0,
            })
            movie['rating_total'] += review.rating
            movie['review_count'] += 1
            movie[f'{sentiment}_review_count'] += 1
            if review.id > movie['first_review_id']:
                movie.update({
                    'director': review.director,
                    'language': review.language,
                    'release_date': review.release_date,
                    'genre': review.genre,
                    'first_review_id': review.id,
                })

        recommendations = []
        for movie in grouped_movies.values():
            movie['genre_label'] = primary_genre(movie['genre'])
            movie['average_rating'] = movie.pop('rating_total') / movie['review_count']
            classified_review_count = (
                movie['positive_review_count'] + movie['negative_review_count']
            )
            movie['positive_percentage'] = (
                movie['positive_review_count'] / classified_review_count * 100
                if classified_review_count
                else 0
            )
            if movie['positive_review_count'] > movie['negative_review_count']:
                movie['sentiment_label'] = 'positive'
            elif movie['negative_review_count'] > movie['positive_review_count']:
                movie['sentiment_label'] = 'negative'
            else:
                movie['sentiment_label'] = 'neutral'
            if filters['movie_type'] and filters['movie_type'] != movie['genre_label']:
                continue
            if filters['language'] and movie['language'] != filters['language']:
                continue
            if filters['director'] and movie['director'] != filters['director']:
                continue
            if filters['sentiment'] and movie['sentiment_label'] != filters['sentiment']:
                continue
            recommendations.append(movie)
        recommendations.sort(
            key=lambda item: (
                -item['positive_percentage'],
                -item['average_rating'],
                item['title'],
            )
        )
    return render(
        request,
        'movie_review_and_movie_recomendation/recommendation.html',
        {'form': form, 'recommendations': recommendations},
    )
