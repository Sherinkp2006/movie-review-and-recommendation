from django import forms

from .genres import primary_genre
from .storage import all_reviews, create_review


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            current_classes = widget.attrs.get('class', '')
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs['class'] = f'{current_classes} form-select'.strip()
            elif isinstance(widget, forms.Textarea):
                widget.attrs.update({
                    'class': f'{current_classes} form-control'.strip(),
                    'rows': 4,
                    'placeholder': 'Share your critical review, highlights, and thoughts...',
                })
            else:
                widget.attrs['class'] = f'{current_classes} form-control'.strip()


class MovieReviewForm(BootstrapFormMixin, forms.Form):
    title = forms.ChoiceField(label='Movie title')
    new_title = forms.CharField(
        label='New movie title',
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Enter full movie title'}),
    )
    new_director = forms.ChoiceField(label='Director', required=False)
    custom_director = forms.CharField(
        label='New director',
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Enter a director'}),
    )
    new_language = forms.ChoiceField(label='Language', required=False)
    custom_language = forms.CharField(
        label='New language',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Enter a language'}),
    )
    new_release_date = forms.DateField(
        label='Release date',
        required=False,
        input_formats=['%d/%m/%Y', '%Y-%m-%d'],
        widget=forms.DateInput(
            format='%d/%m/%Y',
            attrs={'type': 'text', 'placeholder': 'DD/MM/YYYY'},
        ),
    )
    review = forms.CharField(
        widget=forms.Textarea(),
        label='Your review',
    )
    rating = forms.FloatField(
        min_value=0,
        max_value=10,
        widget=forms.NumberInput(attrs={
            'min': '0',
            'max': '10',
            'step': '0.1',
            'placeholder': 'Score (e.g., 8.5)',
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        reviews = all_reviews()
        titles = sorted({item.title for item in reviews})
        directors = sorted({item.director for item in reviews if item.director})
        languages = sorted({item.language for item in reviews if item.language})
        self.fields['title'].choices = [
            ('', 'Select a movie'),
            *[(title, title) for title in titles],
            ('__new__', '+ Add new movie'),
        ]
        self.fields['new_director'].choices = [
            ('', 'Select a director'),
            *[(director, director) for director in directors],
            ('__new__', '+ Add new director'),
        ]
        self.fields['new_language'].choices = [
            ('', 'Select a language'),
            *[(language, language) for language in languages],
            ('__new__', '+ Add new language'),
        ]

    def clean(self):
        cleaned_data = super().clean()
        for field_name in ('review', 'new_title', 'custom_director', 'custom_language'):
            value = cleaned_data.get(field_name)
            if value:
                cleaned_data[field_name] = value.strip()
                if not cleaned_data[field_name]:
                    self.add_error(field_name, 'This field cannot be blank.')

        if cleaned_data.get('title') == '__new__':
            for field_name in ('new_title', 'new_director', 'new_language', 'new_release_date'):
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, 'This field is required for a new movie.')
            if (
                cleaned_data.get('new_language') == '__new__'
                and not cleaned_data.get('custom_language')
            ):
                self.add_error('custom_language', 'Enter the new language.')
            if (
                cleaned_data.get('new_director') == '__new__'
                and not cleaned_data.get('custom_director')
            ):
                self.add_error('custom_director', 'Enter the new director.')
        return cleaned_data

    def save(self):
        selected_title = self.cleaned_data['title']
        if selected_title == '__new__':
            director = self.cleaned_data['new_director']
            if director == '__new__':
                director = self.cleaned_data['custom_director']
            language = self.cleaned_data['new_language']
            if language == '__new__':
                language = self.cleaned_data['custom_language']
            title = self.cleaned_data['new_title']
            release_date = self.cleaned_data['new_release_date']
        else:
            existing_movie = next(
                item for item in all_reviews() if item.title == selected_title
            )
            title = selected_title
            director = existing_movie.director
            language = existing_movie.language
            release_date = existing_movie.release_date

        return create_review(
            title=title,
            director=director,
            language=language,
            release_date=release_date,
            review=self.cleaned_data['review'],
            rating=self.cleaned_data['rating'],
        )


class AdminMovieForm(BootstrapFormMixin, forms.Form):
    title = forms.CharField(label='Movie title', max_length=200)
    director = forms.CharField(label='Director', max_length=200, required=False)
    language = forms.CharField(label='Language', max_length=100, required=False)
    release_date = forms.DateField(
        label='Release date',
        required=False,
        input_formats=['%d/%m/%Y', '%Y-%m-%d'],
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={'type': 'date'},
        ),
    )
    genre = forms.CharField(label='Genre', max_length=200, required=False)
    review = forms.CharField(
        label='Initial review',
        widget=forms.Textarea(),
    )
    rating = forms.FloatField(
        label='Initial rating (0.0 to 10.0)',
        min_value=0,
        max_value=10,
        widget=forms.NumberInput(attrs={'min': '0', 'max': '10', 'step': '0.1'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        title = cleaned_data.get('title')
        if title:
            cleaned_data['title'] = title.strip()
            if not cleaned_data['title']:
                self.add_error('title', 'Enter a movie title.')
        for field_name in ('director', 'language', 'genre', 'review'):
            value = cleaned_data.get(field_name)
            if value:
                cleaned_data[field_name] = value.strip()
        return cleaned_data


class AdminMovieMetadataForm(BootstrapFormMixin, forms.Form):
    title = forms.CharField(label='Movie title', max_length=200)
    director = forms.CharField(label='Director', max_length=200, required=False)
    language = forms.CharField(label='Language', max_length=100, required=False)
    release_date = forms.DateField(
        label='Release date',
        required=False,
        input_formats=['%d/%m/%Y', '%Y-%m-%d'],
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={'type': 'date'},
        ),
    )
    genre = forms.CharField(label='Genre', max_length=200, required=False)

    def clean(self):
        cleaned_data = super().clean()
        title = cleaned_data.get('title')
        if title:
            cleaned_data['title'] = title.strip()
            if not cleaned_data['title']:
                self.add_error('title', 'Enter a movie title.')
        for field_name in ('director', 'language', 'genre'):
            value = cleaned_data.get(field_name)
            if value:
                cleaned_data[field_name] = value.strip()
        return cleaned_data


class AdminReviewForm(BootstrapFormMixin, forms.Form):
    review = forms.CharField(label='Review', widget=forms.Textarea())
    rating = forms.FloatField(
        label='Rating (0.0 to 10.0)',
        min_value=0,
        max_value=10,
        widget=forms.NumberInput(attrs={'min': '0', 'max': '10', 'step': '0.1'}),
    )

    def clean_review(self):
        review_text = self.cleaned_data['review'].strip()
        if not review_text:
            raise forms.ValidationError('Enter the review text.')
        return review_text


class RecommendationForm(BootstrapFormMixin, forms.Form):
    language = forms.ChoiceField(label='Language', required=False)
    director = forms.ChoiceField(label='Director', required=False)
    sentiment = forms.ChoiceField(
        label='Review sentiment',
        required=False,
        choices=(
            ('', 'Any sentiment'),
            ('positive', 'Mostly positive'),
            ('negative', 'Mostly negative'),
        ),
    )
    movie_type = forms.ChoiceField(
        label='Genre',
        required=False,
        choices=(('', 'Any genre'),),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        reviews = all_reviews()
        languages = sorted({item.language for item in reviews if item.language})
        directors = sorted({item.director for item in reviews if item.director})
        genres = sorted(
            {genre for item in reviews if (genre := primary_genre(item.genre))},
            key=str.casefold,
        )
        self.fields['language'].choices = [
            ('', 'Any language'),
            *[(value, value) for value in languages],
        ]
        self.fields['director'].choices = [
            ('', 'Any director'),
            *[(value, value) for value in directors],
        ]
        self.fields['movie_type'].choices = [
            ('', 'Any genre'),
            *[(genre, genre.title()) for genre in genres],
        ]

    def clean(self):
        cleaned_data = super().clean()
        if not any(cleaned_data.values()):
            raise forms.ValidationError('Select at least one recommendation filter.')
        return cleaned_data
