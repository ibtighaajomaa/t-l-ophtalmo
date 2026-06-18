import time
import requests

print('Waiting for Keycloak to be ready...')
while True:
    try:
        response = requests.get('http://localhost:8080/realms/master')
        if response.status_code == 200:
            print('Keycloak is ready!')
            break
    except Exception:
        pass
    print('Still waiting for Keycloak...')
    time.sleep(5)
