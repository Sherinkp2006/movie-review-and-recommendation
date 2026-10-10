from django.urls import path

from . import views

app_name = 'movie_review_and_movie_recomendation'

urlpatterns = [
    path('', views.home, name='home'),
    path('movies/', views.movie_list, name='movie-list'),
    path('movies/<int:movie_id>/', views.movie_reviews, name='movie-reviews'),
    path('reviews/', views.review_list, name='review-list'),
    path('reviews/export-csv/', views.export_reviews_csv, name='review-export-csv'),
    path('reviews/add/', views.add_review, name='add-review'),
    path('recommendations/', views.recommendation, name='recommendation'),
    path(
        'admin-portal/login/',
        views.AdminPortalLoginView.as_view(),
        name='admin-login',
    ),
    path(
        'admin-portal/logout/',
        views.admin_logout,
        name='admin-logout',
    ),
    path('admin-portal/', views.admin_portal, name='admin-portal'),
    path('admin-portal/movies/add/', views.admin_add_movie, name='admin-movie-add'),
    path(
        'admin-portal/movies/<int:movie_id>/edit/',
        views.admin_edit_movie,
        name='admin-movie-edit',
    ),
    path(
        'admin-portal/movies/<int:movie_id>/delete/',
        views.admin_delete_movie,
        name='admin-movie-delete',
    ),
    path(
        'admin-portal/movies/<int:movie_id>/reviews/add/',
        views.admin_add_review,
        name='admin-review-add',
    ),
    path(
        'admin-portal/reviews/<int:review_id>/edit/',
        views.admin_edit_review,
        name='admin-review-edit',
    ),
    path(
        'admin-portal/reviews/<int:review_id>/delete/',
        views.admin_delete_review,
        name='admin-review-delete',
    ),
]
