from django.urls import path
from . import views

urlpatterns = [
    path('api/exams/', views.exam_list, name='exam-list'),
    path('api/exams/stats/', views.exam_stats, name='exam-stats'),
    path('api/exams/sync-orthanc/', views.sync_orthanc, name='exam-sync-orthanc'),
    path('api/exams/<int:pk>/', views.exam_detail, name='exam-detail'),
]
