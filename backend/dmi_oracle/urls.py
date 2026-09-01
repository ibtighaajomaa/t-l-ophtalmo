from django.urls import path

from . import views

urlpatterns = [
    path('api/dmi-oracle/ping/', views.ping, name='dmi-oracle-ping'),
    path('api/dmi-oracle/tables/', views.list_tables, name='dmi-oracle-tables'),
    path('api/dmi-oracle/describe/', views.describe_table, name='dmi-oracle-describe'),
    path('api/dmi-oracle/sample/', views.sample_table, name='dmi-oracle-sample'),
    path('api/dmi-oracle/exams/', views.exams, name='dmi-oracle-exams'),
]
