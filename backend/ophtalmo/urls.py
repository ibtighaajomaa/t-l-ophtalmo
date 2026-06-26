from django.urls import path
from . import views

urlpatterns = [
    path('api/exams/', views.exam_list, name='exam-list'),
    path('api/exams/stats/', views.exam_stats, name='exam-stats'),
    path('api/exams/sync-orthanc/', views.sync_orthanc, name='exam-sync-orthanc'),
    path('api/exams/orthanc-webhook/', views.orthanc_webhook, name='orthanc-webhook'),
    path('api/exams/monai-webhook/', views.monai_inference_webhook, name='monai-inference-webhook'),
    path('api/exams/composite-segmentation/', views.request_composite_segmentation, name='request-composite-segmentation'),
    path('api/exams/distribuer/', views.distribuer_manuellement, name='distribuer-examens'),
    path('api/exams/mes-examens/', views.mes_examens, name='mes-examens'),
    path('api/exams/save-analysis/', views.save_analysis, name='save-analysis'),
    path('api/exams/analysis-reports/', views.list_analysis_reports, name='list-analysis-reports'),
    path('api/exams/generate-report/', views.generate_report, name='generate-report'),
    path('api/exams/medical-reports/', views.medical_report_list, name='medical-report-list'),
    path('api/exams/medical-reports/<int:pk>/', views.medical_report_detail, name='medical-report-detail'),
    path('api/exams/medical-reports/<int:pk>/sign/', views.sign_medical_report, name='sign-medical-report'),
    path('api/exams/medical-reports/<int:pk>/versions/', views.list_report_versions, name='list-report-versions'),
    path('api/exams/medical-reports/<int:pk>/export-docx/', views.export_report_docx, name='export-report-docx'),
    path('api/exams/<int:pk>/', views.exam_detail, name='exam-detail'),
    path('api/exams/<int:pk>/terminer/', views.terminer_examen, name='terminer-examen'),
    path('api/medecins/disponibilite/', views.toggle_disponibilite, name='toggle-disponibilite'),
]
