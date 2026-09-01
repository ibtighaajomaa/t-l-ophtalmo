"""HTTP endpoints for the DMI Oracle connection, for Postman testing.

ping/tables/describe are open (metadata only, safe to poke while wiring
things up). sample/exams touch real rows and require the same
X-DMI-Service-Token header as the existing /api/dmi/ HTTP integration
(see ophtalmo.dmi_integration.is_valid_dmi_request).
"""
import re

from django.db import connections
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ophtalmo.dmi_integration import is_valid_dmi_request

from .models import MdExamOphtalmo

IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$#]*$')


def _dmi_db_available():
    return 'dmi_db' in connections.databases


def _not_configured():
    return Response(
        {'error': "dmi_db is not configured. Set ORACLE_DMI_HOST (and _PORT/_SERVICE_NAME/_USER/_PASSWORD)."},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _unauthorized():
    return Response(
        {'error': 'Missing or invalid X-DMI-Service-Token header'},
        status=status.HTTP_401_UNAUTHORIZED,
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def ping(request):
    if not _dmi_db_available():
        return _not_configured()
    try:
        with connections['dmi_db'].cursor() as cursor:
            cursor.execute("SELECT 1 FROM DUAL")
            cursor.fetchone()
    except Exception as exc:
        return Response({'status': 'error', 'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([AllowAny])
def list_tables(request):
    if not _dmi_db_available():
        return _not_configured()
    pattern = (request.query_params.get('like') or '%').upper()
    try:
        with connections['dmi_db'].cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM user_tables WHERE table_name LIKE :1 ORDER BY table_name",
                [pattern],
            )
            rows = [r[0] for r in cursor.fetchall()]
    except Exception as exc:
        return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({'tables': rows})


@api_view(['GET'])
@permission_classes([AllowAny])
def describe_table(request):
    if not _dmi_db_available():
        return _not_configured()
    table = request.query_params.get('table')
    if not table or not IDENTIFIER_RE.match(table):
        return Response({'error': 'Invalid or missing table query param'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        with connections['dmi_db'].cursor() as cursor:
            cursor.execute(
                "SELECT column_name, data_type, data_length, nullable "
                "FROM user_tab_columns WHERE table_name = :1 ORDER BY column_id",
                [table.upper()],
            )
            columns = [
                {'name': name, 'type': data_type, 'length': length, 'nullable': nullable == 'Y'}
                for name, data_type, length, nullable in cursor.fetchall()
            ]
    except Exception as exc:
        return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    if not columns:
        return Response({'error': f'Table not found or inaccessible: {table}'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'table': table.upper(), 'columns': columns})


@api_view(['GET'])
@permission_classes([AllowAny])
def sample_table(request):
    if not _dmi_db_available():
        return _not_configured()
    if not is_valid_dmi_request(request):
        return _unauthorized()
    table = request.query_params.get('table')
    if not table or not IDENTIFIER_RE.match(table):
        return Response({'error': 'Invalid or missing table query param'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        limit = max(1, min(int(request.query_params.get('limit', 5)), 100))
    except ValueError:
        limit = 5
    try:
        with connections['dmi_db'].cursor() as cursor:
            cursor.execute(f"SELECT * FROM {table} WHERE ROWNUM <= {limit}")
            col_names = [c[0] for c in cursor.description]
            rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]
    except Exception as exc:
        return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({'table': table.upper(), 'rows': rows})


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def exams(request):
    """GET: list a few rows via the ORM model. POST: insert a test row.

    The model's columns are a guess (see dmi_oracle/models.py) — adjust
    both once `describe` confirms the real schema.
    """
    if not _dmi_db_available():
        return _not_configured()
    if not is_valid_dmi_request(request):
        return _unauthorized()

    if request.method == 'GET':
        try:
            queryset = MdExamOphtalmo.objects.using('dmi_db').all()[:20]
            data = [
                {
                    'num_resume': e.num_resume,
                    'date_examen': e.date_examen,
                    'cod_med': e.cod_med,
                    'provenance': e.provenance,
                }
                for e in queryset
            ]
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({'count': len(data), 'results': data})

    payload = request.data
    required = ['num_resume', 'date_examen', 'cod_med', 'provenance']
    missing = [f for f in required if f not in payload]
    if missing:
        return Response({'error': f"Missing fields: {', '.join(missing)}"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        exam = MdExamOphtalmo(
            num_resume=payload['num_resume'],
            date_examen=payload['date_examen'],
            cod_med=payload['cod_med'],
            provenance=payload['provenance'],
        )
        exam.save(using='dmi_db')
    except Exception as exc:
        return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({'status': 'created', 'num_resume': exam.num_resume}, status=status.HTTP_201_CREATED)
