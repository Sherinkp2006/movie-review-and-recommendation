from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class AdminPortalSessionMiddleware(MiddlewareMixin):
    session_key = 'movie_review_and_movie_recomendation_admin_portal'

    def process_view(self, request, _view_func, _view_args, _view_kwargs):
        admin_portal_prefix = '/admin-portal/'
        static_url = settings.STATIC_URL
        if (
            self.session_key in request.session
            and not request.path.startswith(admin_portal_prefix)
            and not request.path.startswith(static_url)
        ):
            del request.session[self.session_key]
        return None
