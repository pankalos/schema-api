import os
from pathlib import Path

from django.core.exceptions import NON_FIELD_ERRORS

from config.settings.api import *
from config.settings.api_auth import *
from config.settings.files import *
from config.env import env

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'django_filters',
    'core',
    'api_auth',
    'quotas',
    'api',
    'files',
    'workflows',
    'experiments',
    'graphene_django',
    'drf_spectacular',
    'api_streaming',
    'api_streaming_influx',
    'api_streaming_timescale',
    'api_streaming_leaf_influx'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'schema_api.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'schema_api.wsgi.application'

# Password validation
# https://docs.djangoproject.com/en/4.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/4.1/topics/i18n/

LANGUAGE_CODE = env.str('SCHEMA_API_LANGUAGE_CODE', 'en-us')

TIME_ZONE = env.str('SCHEMA_API_TIME_ZONE', 'UTC')

USE_I18N = env.bool('SCHEMA_API_USE_I18N', True)

USE_TZ = env.bool('SCHEMA_API_USE_TZ', True)

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.1/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static/')
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Default primary key field type
# https://docs.djangoproject.com/en/4.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer'
    ],
    'DEFAULT_FILTER_BACKENDS': ('django_filters.rest_framework.DjangoFilterBackend',),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'EXCEPTION_HANDLER': 'util.exceptions.custom_exception_handler'
}

GRAPHENE = {
    'SCHEMA': 'monitor.schema.schema'
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Schema API',
    'DESCRIPTION': 'A REST API for the scheduling and execution of containerized tasks',
    'VERSION': 'development',
    'SERVE_INCLUDE_SCHEMA': False,
    'PARSER_WHITELIST': ['rest_framework.parsers.JSONParser'],
    'SWAGGER_UI_SETTINGS': {
        'defaultModelsExpandDepth': 10,
        'defaultModelExpandDepth': 10
    },
    "PREPROCESSING_HOOKS": ["documentation.swagger.hooks.preprocessing_filter_spec"],

}

AUTH_USER_MODEL = 'api_auth.AuthEntity'

MIGRATION_MODULES = {
    'api': 'migrations.api',
    'api_auth': 'migrations.api_auth',
    'experiments': 'migrations.experiments',
    'files': 'migrations.files',
    'monitor': 'migrations.monitor',
    'quotas': 'migrations.quotas',
    'workflows': 'migrations.workflows',
    'api_streaming': 'migrations.api_streaming',
    'api_streaming_influx': 'migrations.api_streaming_influx',
    'api_streaming_timescale': 'migrations.api_streaming_timescale',
    'api_streaming_leaf_influx': 'migrations.api_streaming_leaf_influx'
}

POSTGRES_DATABASE_CONFIGURATION = {
    'ENGINE': 'django.db.backends.postgresql',
    'USER': env.str('SCHEMA_API_DB_USER', 'schema-api'),
    'NAME': env.str('SCHEMA_API_DB_NAME', 'schema-api-db'),
    'HOST': env.str('SCHEMA_API_DB_HOST', '127.0.0.1'),
    'PORT': env.str('SCHEMA_API_DB_PORT', '5432'),
}

SQLITE_DATABASE_CONFIGURATION = {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': os.path.join(
        env.str('SCHEMA_API_SQLITE_DIRECTORY', BASE_DIR),
        f'{env.str("SCHEMA_API_DB_NAME", "schema-api-db")}.sqlite3'
    ),
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f'redis://{env.str("SCHEMA_API_CACHE_REDIS_HOST")}/'
                    f'{env.int("SCHEMA_API_CACHE_REDIS_DB_INDEX", "1")}',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient'
        },
    } if env.bool('SCHEMA_API_ENABLE_CACHE', False) else {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache"
    }
}
CACHE_TIMEOUT = env.int('SCHEMA_API_CACHE_TIMEOUT_SECONDS', 15)

# This is the pattern that matches outputs generated by Django's slugify function
# NOTE: this is not the same pattern of values accepted by Django's and DRF's SlugFields
DJANGO_SLUG_PATTERN = '[a-z0-9][-a-z0-9]+'
APPLICATION_SLUG_PATTERN = env.str('SCHEMA_API_SLUG_PATTERN', DJANGO_SLUG_PATTERN)

NON_FIELD_ERRORS_KEY = env.str('SCHEMA_API_NON_FIELD_ERRORS_KEY', NON_FIELD_ERRORS)

# Overriding/setting missing application-related settings

if not USERNAME_SLUG_PATTERN:
    USERNAME_SLUG_PATTERN = APPLICATION_SLUG_PATTERN

if not USERNAME_SLUG_PATTERN_VIOLATION_MESSAGE:
    # noinspection PyUnboundLocalVariable
    USERNAME_SLUG_PATTERN_VIOLATION_MESSAGE = 'Username must abide by the following regular expression: ' \
                                              f'{USERNAME_SLUG_PATTERN}'

if CONTEXT_NAME_SLUG_PATTERN is None:
    CONTEXT_NAME_SLUG_PATTERN = APPLICATION_SLUG_PATTERN

if not CONTEXT_NAME_SLUG_PATTERN_VIOLATION_MESSAGE:
    # noinspection PyUnboundLocalVariable
    CONTEXT_NAME_SLUG_PATTERN_VIOLATION_MESSAGE = 'Context name must abide by the following regular expression: ' \
                                                  f'{CONTEXT_NAME_SLUG_PATTERN}'

MAX_PAGINATION_LIMIT = env.int('SCHEMA_API_MAX_PAGINATION_LIMIT', 100)
DEFAULT_PAGINATION_LIMIT = env.int('SCHEMA_API_DEFAULT_PAGINATION_LIMIT', 50)
