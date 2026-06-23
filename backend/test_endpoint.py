import requests

url = "http://localhost:8001/api/auth/register-user/"
payload = {
    "email": "test@gmail.com",
    "prenom": "test",
    "nom": "test",
    "role": "OPHTALMOLOGUE",
    "password_provisoire": "test1234"
}
headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)
print(f"Status Code: {response.status_code}")
print(f"Response Body: {response.text}")
