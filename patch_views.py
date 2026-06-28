import re

with open('backend/users/views.py', 'r') as f:
    content = f.read()

# Replace assign_session and append the other functions
match = re.search(r'@api_view\(\[\'POST\'\]\)\n@permission_classes\(\[permissions\.AllowAny\]\)\ndef assign_session\(request\):', content)
if match:
    new_content = content[:match.start()] + """@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def assign_session(request):
    \"\"\"
    Crée N examens 'En cours' assignés au médecin ciblé,
    et met à jour sa charge_actuelle.
    \"\"\"
    email = request.data.get('email')
    try:
        count = int(request.data.get('count', 1))
    except (ValueError, TypeError):
        count = 1
        
    start_hour = int(request.data.get('startHour', 8))
    end_hour = int(request.data.get('endHour', 10))
    date_str = request.data.get('date')
    
    if not email:
        return Response({'error': 'Email requis'}, status=400)
        
    try:
        from django.contrib.auth.models import User
        from ophtalmo.models import Exam, CalendarSession
        from datetime import date, datetime
        
        try:
            user = User.objects.get(username__iexact=email)
        except User.DoesNotExist:
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                return Response({'error': 'Utilisateur introuvable'}, status=404)

        if date_str:
            try:
                session_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                session_date = date.today()
        else:
            session_date = date.today()

        profil = user.profil
        
        restant = max(0, 30 - profil.charge_actuelle)
        a_assigner = min(count, restant)
        
        if a_assigner <= 0:
            return Response({'error': 'Capacité maximale atteinte (30/30).'}, status=400)
            
        for i in range(a_assigner):
            Exam.objects.create(
                patient_name=f"Patient Assigné ({i+1})",
                exam_type="Rétinographie",
                date=session_date,
                status="En cours",
                priority="Normal",
                assigned_to=user
            )
            
        profil.charge_actuelle += a_assigner
        profil.save(update_fields=['charge_actuelle'])
        
        session_obj = CalendarSession.objects.create(
            doctor=user,
            date=session_date,
            start_hour=start_hour,
            end_hour=end_hour,
            count=a_assigner,
            affiliation="Assignation manuelle",
            hospital="Cabinet"
        )
        
        role = user.profil.role if hasattr(user, 'profil') else "Medecin"
        title = "Pr" if role == "Chef" else "Dr"
        
        return Response({
            'message': f'{a_assigner} examens assignés au Dr {user.last_name}', 
            'assigned': a_assigner,
            'session': {
                'id': session_obj.id,
                'doctorName': f"{title} {user.first_name} {user.last_name}".strip(),
                'email': user.email,
                'date': session_obj.date.isoformat(),
                'startHour': session_obj.start_hour,
                'endHour': session_obj.end_hour,
                'count': session_obj.count,
                'affiliation': session_obj.affiliation,
                'hospital': session_obj.hospital,
                'parsedDate': session_obj.date.isoformat()
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': str(e)}, status=500)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_sessions(request):
    from ophtalmo.models import CalendarSession
    sessions = CalendarSession.objects.all()
    data = []
    for s in sessions:
        role = s.doctor.profil.role if hasattr(s.doctor, 'profil') else "Medecin"
        title = "Pr" if role == "Chef" else "Dr"
        data.append({
            'id': s.id,
            'doctorName': f"{title} {s.doctor.first_name} {s.doctor.last_name}".strip(),
            'email': s.doctor.email,
            'date': s.date.isoformat(),
            'startHour': s.start_hour,
            'endHour': s.end_hour,
            'count': s.count,
            'affiliation': s.affiliation,
            'hospital': s.hospital,
            'parsedDate': s.date.isoformat()
        })
    return Response({'sessions': data})

@api_view(['DELETE'])
@permission_classes([permissions.AllowAny])
def delete_session(request, session_id):
    from ophtalmo.models import CalendarSession
    try:
        session_obj = CalendarSession.objects.get(id=session_id)
        session_obj.delete()
        return Response({'message': 'Session supprimée'})
    except CalendarSession.DoesNotExist:
        return Response({'error': 'Session introuvable'}, status=404)

@api_view(['PUT'])
@permission_classes([permissions.AllowAny])
def update_session(request, session_id):
    from ophtalmo.models import CalendarSession
    from django.contrib.auth.models import User
    try:
        session_obj = CalendarSession.objects.get(id=session_id)
        email = request.data.get('email')
        if email:
            try:
                user = User.objects.get(email__iexact=email)
                session_obj.doctor = user
            except User.DoesNotExist:
                pass
        
        session_obj.start_hour = int(request.data.get('startHour', session_obj.start_hour))
        session_obj.end_hour = int(request.data.get('endHour', session_obj.end_hour))
        session_obj.count = int(request.data.get('count', session_obj.count))
        session_obj.save()
        
        role = session_obj.doctor.profil.role if hasattr(session_obj.doctor, 'profil') else "Medecin"
        title = "Pr" if role == "Chef" else "Dr"
        
        return Response({'message': 'Session modifiée', 'session': {
            'id': session_obj.id,
            'doctorName': f"{title} {session_obj.doctor.first_name} {session_obj.doctor.last_name}".strip(),
            'email': session_obj.doctor.email,
            'date': session_obj.date.isoformat(),
            'startHour': session_obj.start_hour,
            'endHour': session_obj.end_hour,
            'count': session_obj.count,
            'affiliation': session_obj.affiliation,
            'hospital': session_obj.hospital,
            'parsedDate': session_obj.date.isoformat()
        }})
    except CalendarSession.DoesNotExist:
        return Response({'error': 'Session introuvable'}, status=404)
"""
    with open('backend/users/views.py', 'w') as f:
        f.write(new_content)
    print("Patched successfully")
else:
    print("Could not find assign_session")
