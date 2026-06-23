import os
import time
import requests

keycloak_url = os.environ.get('KEYCLOAK_SERVER_URL', 'http://localhost:8080/').rstrip('/')

print(f'Waiting for Keycloak at {keycloak_url}...')
while True:
    try:
        response = requests.get(f'{keycloak_url}/realms/master')
        if response.status_code == 200:
            print('Keycloak is ready!')
            break
    except Exception:
        pass
    print('Still waiting for Keycloak...')
    time.sleep(5)
